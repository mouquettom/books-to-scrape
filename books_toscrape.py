from bs4 import BeautifulSoup
import requests
from loguru import logger
from urllib.parse import urljoin
import re
import csv
import pathlib


BASE_URL = "http://books.toscrape.com"

user_agent = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
              "Version/14.1 Safari/605.1.15")

headers = {"User-Agent": user_agent}

# Délai maximal (en secondes) accordé à chaque requête HTTP
TIMEOUT = 10


def get_page(session, url):
    """Récupère une page et renvoie son contenu analysé, ou None en cas d'erreur."""

    try:
        response = session.get(url, headers=headers, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur lors de la requête HTTP {url} : {e}")
        return None

    # Le site ne précise pas l'encodage dans ses en-têtes : sans cette ligne,
    # requests suppose ISO-8859-1 et les caractères spéciaux sont mal décodés (ex. "Â£").
    response.encoding = "utf-8"

    return BeautifulSoup(response.text, "html.parser")


def get_categories_urls():

    category_urls = []

    with requests.Session() as session:

        soup = get_page(session, BASE_URL)
        if soup is None:
            return category_urls

        categories = soup.find("ul", class_="nav nav-list").find("ul").find_all("a")
        categories_urls = [category["href"] for category in categories]

        for category_url in categories_urls:
            absolute_url = urljoin(BASE_URL, category_url)
            category_urls.append(absolute_url)
        return category_urls


def get_all_books_urls(url):

    books_urls = []

    with requests.Session() as session:

        while url:
            logger.info(f"Scraping page at {url}")

            soup = get_page(session, url)
            if soup is None:
                break

            all_urls = get_all_books_urls_on_page(url, soup)
            books_urls.extend(all_urls)

            url = get_next_page(url, soup)

        return books_urls


def get_next_page(url, soup):

    try:
        next_page_url = soup.find("li", class_="next").find("a")["href"]
        return urljoin(url, next_page_url)
    except (AttributeError, KeyError, TypeError):
        logger.info("Aucun bouton 'next' trouvé sur la page.")
        return None


def get_all_books_urls_on_page(url, soup):

    books_urls_on_page = []

    try:
        articles = soup.find_all("article", class_="product_pod")
        for article in articles:
            book_url = article.find("h3").find("a")["href"]
            absolute_book_url = urljoin(url, book_url)
            books_urls_on_page.append(absolute_book_url)
        return books_urls_on_page
    except (AttributeError, KeyError, TypeError):
        logger.error(f"Impossible de lire la liste des livres sur la page {url}")
        return []


def infos_book(session, url):

    logger.info(f"Scraping book at {url}")

    soup = get_page(session, url)
    if soup is None:
        return None

    category = soup.find("ul", class_="breadcrumb").find_all("li")[2].text.strip()
    title = soup.find("h1").text

    price_node = soup.find("p", class_="price_color").text
    price = str(re.findall(r"[0-9.]+", price_node)[0])

    stock = soup.find("p", class_="instock availability").text.strip()

    star = soup.find("p", class_="star-rating")["class"][1]
    if star == "One":
        star = 1
    elif star == "Two":
        star = 2
    elif star == "Three":
        star = 3
    elif star == "Four":
        star = 4
    elif star == "Five":
        star = 5

    # La description est le paragraphe qui suit le bloc "Product Description" (absent pour certains livres)
    description_header = soup.find("div", id="product_description")
    description_node = description_header.find_next_sibling("p") if description_header else None
    description = description_node.text if description_node else ""

    image_node = soup.find("img")["src"][6:]
    image_url = urljoin(BASE_URL, image_node)

    rows = soup.find_all("tr")
    upc = rows[0].find("td").text
    product_type = rows[1].find("td").text
    price_excl_tax = rows[2].find("td").text
    price_incl_tax = rows[3].find("td").text
    tax = rows[4].find("td").text
    nb_of_reviews = rows[6].find("td").text

    infos = {
        'Category': category,
        'Title': title,
        'Price': price,
        'Stock': stock,
        'Star': star,
        'Description': description,
        'Image': image_url,
        'URL': url,
        'UPC': upc,
        'Product Type': product_type,
        'Price (excl.tax)': price_excl_tax,
        'Price (incl.tax)': price_incl_tax,
        'Tax': tax,
        'Nb of reviews': nb_of_reviews
    }

    return infos


def main():

    all_books_urls = []

    for category_url in get_categories_urls():
        all_urls = get_all_books_urls(url=category_url)
        all_books_urls.extend(all_urls)

    data_books = []

    with requests.Session() as session:
        for book_url in all_books_urls:
            infos = infos_book(session, url=book_url)
            if infos is not None:
                data_books.append(infos)

    if not data_books:
        logger.error("Aucun livre récupéré : aucun fichier n'a été créé.")
        return

    write_csv(data_books)

    download_images(data_books)


def write_csv(data_books):

    root_path = pathlib.Path(__file__).parent.resolve()
    path = pathlib.Path(root_path / "data")

    path.mkdir(parents=True, exist_ok=True)

    category = ""
    csvfile = None
    writer = None

    fieldnames = ['Category', 'Title', 'Price', 'Stock', 'Star', 'Description', 'Image', 'URL', 'UPC',
                  'Product Type', 'Price (excl.tax)', 'Price (incl.tax)', 'Tax', 'Nb of reviews']

    for book in data_books:
        if category != book['Category']:
            category = book['Category']

            if csvfile is not None:
                csvfile.close()

            filename = category + ".csv"

            csvfile = open(path / filename, 'w', newline="", encoding="utf-8")

            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()

        writer.writerow(book)

    if csvfile is not None:
        csvfile.close()


def download_images(data_books):

    root_path = pathlib.Path(__file__).parent.resolve()
    path = pathlib.Path(root_path / "images")

    path.mkdir(parents=True, exist_ok=True)

    with requests.Session() as session:
        for book in data_books:
            try:
                response = session.get(book["Image"], headers=headers, timeout=TIMEOUT)
                response.raise_for_status()
            except requests.exceptions.RequestException as e:
                logger.error(f"Erreur lors du téléchargement de l'image {book['Image']} : {e}")
                continue

            filename = book["Image"].split('/')[-1]

            with open(path / filename, "wb") as file:
                file.write(response.content)


if __name__ == "__main__":
    main()
