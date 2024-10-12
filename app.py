from flask import Flask, render_template, jsonify
import requests
from bs4 import BeautifulSoup
import gc  
import logging
import json
from ratelimit import limits, sleep_and_retry  

app = Flask(__name__)

# Set up for logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Loading configuration from JSON file
with open('config.json', 'r') as f:
    config = json.load(f)

API_KEY = config['API_KEY']
CALLS_PER_SECOND = 1
SECONDS_PER_CALL = 1 / CALLS_PER_SECOND


@sleep_and_retry
@limits(calls=CALLS_PER_SECOND, period=SECONDS_PER_CALL)
def make_request(url, headers=None):
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Raise an error for bad responses
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        logging.error(f"HTTP error occurred: {http_err}")
    except Exception as err:
        logging.error(f"An error occurred: {err}")
    return None


class GoogleScholarScraper:
    def __init__(self):
        pass

    def get_data_from_profile_link(self, profile_link):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

        try:
            # Use response streaming to reduce memory usage
            response = requests.get(profile_link, headers=headers, stream=True)

            if response.status_code == 200:
                # Use `lxml` parser for efficient parsing
                soup = BeautifulSoup(response.content, 'lxml')

                # Extract name
                name_element = soup.find('div', {'id': 'gsc_prf_in'})
                name = name_element.text.strip() if name_element else "Name not found"

                # Extract citations, h-index, and i10-index
                citation_table = soup.find_all('td', {'class': 'gsc_rsb_std'})
                if len(citation_table) >= 3:
                    citations = int(citation_table[0].text.strip()) if citation_table[0].text else 0
                    h_index = citation_table[1].text.strip() if citation_table[1].text else "H-Index not found"
                    i10_index = citation_table[2].text.strip() if citation_table[2].text else "i10-Index not found"
                else:
                    citations, h_index, i10_index = 0, "H-Index not found", "i10-Index not found"

                # Fetch yearly citations (optimized year range)
                yearly_citations = {}
                graph_element = soup.find('div', {'id': 'gsc_rsb_cit'})
                if graph_element:
                    bar_elements = graph_element.find_all('span', {'class': 'gsc_g_t'})
                    value_elements = graph_element.find_all('span', {'class': 'gsc_g_al'})

                    for year_element, count_element in zip(bar_elements, value_elements):
                        year = int(year_element.text.strip())
                        count = int(count_element.text.strip())
                        if 2020 <= year <= 2024:  # Adjust the year range as needed
                            yearly_citations[str(year)] = count

                # Fetch papers details (title, citations, year)
                papers = []
                paper_elements = soup.find_all('tr', {'class': 'gsc_a_tr'})
                for paper_element in paper_elements:
                    title_element = paper_element.find('a', {'class': 'gsc_a_at'})
                    title = title_element.text if title_element else "No Title"
                    link = f"https://scholar.google.com{title_element['href']}" if title_element else "#"

                    citation_element = paper_element.find('a', {'class': 'gsc_a_ac'})
                    paper_citations = citation_element.text.strip() if citation_element and citation_element.text else "0"

                    year_element = paper_element.find('span', {'class': 'gsc_a_h'})
                    year = year_element.text.strip() if year_element else "Unknown Year"

                    papers.append({
                        'title': title,
                        'link': link,
                        'citations': paper_citations,
                        'year': year
                    })

                # Explicitly clear memory for large variables
                del soup
                gc.collect()  # Perform garbage collection to free up memory

                return {
                    'Name': name,
                    'Citations': citations,
                    'H_Index': h_index,
                    'i10_Index': i10_index,
                    'Yearly_Citations': yearly_citations,
                    'Papers': papers
                }
            else:
                return {'error': f'Failed to retrieve data. Status code: {response.status_code}'}
        except Exception as e:
            return {'error': str(e)}

    def scraping_multiple_faculties(self, profile_links):
        data_list = []
        for profile_link in profile_links:
            faculty_data = self.get_data_from_profile_link(profile_link)
            if faculty_data:
                data_list.append(faculty_data)
            # Perform garbage collection after each faculty to free up memory
            gc.collect()
        return data_list


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/scrape', methods=['GET'])
def scrape():
    profile_links = [
        "https://scholar.google.com/citations?user=fzs9d1IAAAAJ&hl=en",
        "https://scholar.google.com/citations?user=-ZYIiGAAAAAJ&hl=en",
    ]

    scraper = GoogleScholarScraper()
    google_scholar_data = scraper.scraping_multiple_faculties(profile_links)

    return jsonify({'google_scholar_data': google_scholar_data})


@app.route('/scopus-scrape', methods=['GET'])
def scopus_scrape():
    profile_links = [
        "https://www.scopus.com/authid/detail.uri?authorId=57223100630",
        "https://www.scopus.com/authid/detail.uri?authorId=55079543700",
        "https://www.scopus.com/authid/detail.uri?authorId=35737586100",
    ]

    headers = {"X-ELS-APIKey": API_KEY, "Accept": "application/json"}
    all_data = []

    for link in profile_links:
        author_id = link.split('authorId=')[-1]
        # Adjusted API query URL based on correct Scopus parameters
        base_url = "https://api.elsevier.com/content/search/scopus"
        query = f"?query=AU-ID({author_id})&date=2023-2024"

        # Make the request
        response = make_request(base_url + query, headers=headers)

        if response:
            articles = response.get("search-results", {}).get("entry", [])
            
            # Process articles
            for entry in articles:
                all_data.append({
                    "title": entry.get("dc:title", "No Title"),
                    "creator": entry.get("dc:creator", "No Author"),
                    "publisher": entry.get("prism:publicationName", "No Publisher"),
                    "date": entry.get("prism:coverDate", "No Date"),
                    "doi": entry.get("prism:doi", "No DOI"),
                    "citations": entry.get("citedby-count", "No Data")
                })
        else:
            logging.error(f"Failed to retrieve data for author ID: {author_id}")

    return jsonify({'scopus_data': all_data})


@app.route('/combined-scrape', methods=['GET'])
def combined_scrape():
    # Fetch Google Scholar Data
    profile_links = [
        "https://scholar.google.com/citations?user=fzs9d1IAAAAJ&hl=en",
        "https://scholar.google.com/citations?user=-ZYIiGAAAAAJ&hl=en",
        "https://scholar.google.com/citations?user=vGJxAzEAAAAJ&hl=en"
    ]

    scraper = GoogleScholarScraper()
    google_scholar_data = scraper.scraping_multiple_faculties(profile_links)

    # Fetch Scopus Data
    scopus_profile_links = [
        "https://www.scopus.com/authid/detail.uri?authorId=57223100630",
        "https://www.scopus.com/authid/detail.uri?authorId=55079543700",
        "https://www.scopus.com/authid/detail.uri?authorId=35737586100",
    ]

    headers = {"X-ELS-APIKey": API_KEY, "Accept": "application/json"}
    all_data = []

    for link in scopus_profile_links:
        author_id = link.split('authorId=')[-1]
        # Adjusted API query URL based on correct Scopus parameters
        base_url = "https://api.elsevier.com/content/search/scopus"
        query = f"?query=AU-ID({author_id})&date=2023-2024"

        # Make the request
        response = make_request(base_url + query, headers=headers)

        if response:
            articles = response.get("search-results", {}).get("entry", [])
            
            # Process articles
            for entry in articles:
                all_data.append({
                    "title": entry.get("dc:title", "No Title"),
                    "creator": entry.get("dc:creator", "No Author"),
                    "publisher": entry.get("prism:publicationName", "No Publisher"),
                    "date": entry.get("prism:coverDate", "No Date"),
                    "doi": entry.get("prism:doi", "No DOI"),
                    "citations": entry.get("citedby-count", "No Data")
                })
        else:
            logging.error(f"Failed to retrieve data for author ID: {author_id}")

    return jsonify({
        'google_scholar_data': google_scholar_data,
        'scopus_data': all_data
    })


if __name__ == '__main__':
    app.run(debug=True)
