"""
jobspy.scrapers.linkedin
~~~~~~~~~~~~~~~~~~~

This module contains routines to scrape LinkedIn.
"""
import time
from typing import Optional
from datetime import datetime

import requests
import time
import re
from requests.exceptions import ProxyError
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from bs4.element import Tag
from threading import Lock

from .. import Scraper, ScraperInput, Site
from ..exceptions import LinkedInException
from ...jobs import (
    JobPost,
    Location,
    JobResponse,
    JobType,
)
import urllib.parse

def extract_emails_from_text(text: str) -> Optional[list[str]]:
    if not text:
        return None
    email_regex = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    return email_regex.findall(text)


class LinkedInScraper(Scraper):
    MAX_RETRIES = 3
    DELAY = 10

    def __init__(self, proxy: Optional[str] = None):
        """
        Initializes LinkedInScraper with the LinkedIn job search url
        """
        site = Site(Site.LINKEDIN)
        self.country = "worldwide"
        self.url = "https://www.linkedin.com"
        super().__init__(site, proxy=proxy)
        self.max_job = 300
        self.job_count = 0
        self.proxy_config = {
            "http": proxy,
            "https": proxy,
        }

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        """
        Scrapes LinkedIn for jobs with scraper_input criteria
        :param scraper_input:
        :return: job_response
        """
        job_list: list[JobPost] = []
        seen_urls = set()
        url_lock = Lock()
        page = scraper_input.offset // 25 + 25 if scraper_input.offset else 0

        def job_type_code(job_type_enum):
            mapping = {
                JobType.FULL_TIME: "F",
                JobType.PART_TIME: "P",
                JobType.INTERNSHIP: "I",
                JobType.CONTRACT: "C",
                JobType.TEMPORARY: "T",
            }

            return mapping.get(job_type_enum, "")

        while len(job_list) < scraper_input.results_wanted and page < 1000:
            params = {
                "keywords": scraper_input.search_term,
                "location": scraper_input.location,
                "distance": scraper_input.distance,
                "f_WT": 2 if scraper_input.is_remote else None,
                "f_JT": job_type_code(scraper_input.job_type)
                if scraper_input.job_type
                else None,
                "pageNum": 0,
                page: page + scraper_input.offset,
                "f_AL": "true" if scraper_input.easy_apply else None,
            }

            #serach with keywords
            if scraper_input.search_term.find('https') == -1:
                params = {k: v for k, v in params.items() if v is not None}
            else:
                params['keywords'] =''
                parsed_url = urllib.parse.urlparse(scraper_input.search_term)
                captured_value = urllib.parse.parse_qs(parsed_url.query)
                for url_key in captured_value:
                    params[url_key]=captured_value[url_key][0]
                params['pageNum'] = page
                params = {k: v for k, v in params.items() if v is not None}

            retries = 0
            while retries < self.MAX_RETRIES:
                try:
                    # print(params)
                    session = requests.Session()
                    response = session.get(
                        f"{self.url}/jobs-guest/jobs/api/seeMoreJobPostings/search?",
                        headers={
                                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/78.0.3904.97 Safari/537.36"
                                },
                    params=params,
                    allow_redirects=True,
                    proxies=self.proxy,
                    timeout=20,
                    )
                    time.sleep(1)
                    print(response.url)
                    response.raise_for_status()

                    break
                except requests.HTTPError as e:
                    if hasattr(e, 'response') and e.response is not None:
                        if e.response.status_code == 429:
                            time.sleep(self.DELAY)
                            retries += 1
                            continue
                        else:
                            raise LinkedInException(f"bad response status code: {e.response.status_code}")
                    else:
                        raise
                except ProxyError as e:
                    raise LinkedInException("bad proxy")
                except Exception as e:
                    raise LinkedInException(str(e))
            else:
                # Raise an exception if the maximum number of retries is reached
                raise LinkedInException("Max retries reached, failed to get a valid response")

            soup = BeautifulSoup(response.text, "html.parser")

            with ThreadPoolExecutor(git=1) as executor:
                futures = []
                for job_card in soup.find_all("div", class_="base-search-card"):
                    job_url = None
                    href_tag = job_card.find("a", class_="base-card__full-link")
                    if href_tag and "href" in href_tag.attrs:
                        href = href_tag.attrs["href"].split("?")[0]
                        job_id = href.split("-")[-1]
                        job_url = f"{self.url}/jobs/view/{job_id}"

                    with url_lock:
                        if job_url in seen_urls:
                            continue
                        if self.check_exist(job_url):
                            time.sleep(0.1)
                            continue
                        seen_urls.add(job_url)

                    futures.append(executor.submit(self.process_job, job_card, job_url))

                for future in as_completed(futures):
                    try:
                        job_post = future.result()
                        if job_post:
                            job_list.append(job_post)
                    except Exception as e:
                        raise LinkedInException("Exception occurred while processing jobs")
            page += 25

        job_list = job_list[: scraper_input.results_wanted]
        return JobResponse(jobs=job_list)

    def process_job(self, job_card: Tag, job_url: str) -> Optional[JobPost]:
        title_tag = job_card.find("span", class_="sr-only")
        title = title_tag.get_text(strip=True) if title_tag else "N/A"

        company_tag = job_card.find("h4", class_="base-search-card__subtitle")
        company_a_tag = company_tag.find("a") if company_tag else None
        company = company_a_tag.get_text(strip=True) if company_a_tag else "N/A"

        metadata_card = job_card.find("div", class_="base-search-card__metadata")
        location = self.get_location(metadata_card)

        datetime_tag = metadata_card.find("time", class_="job-search-card__listdate") if metadata_card else None
        date_posted = None
        if datetime_tag and "datetime" in datetime_tag.attrs:
            datetime_str = datetime_tag["datetime"]
            try:
                date_posted = datetime.strptime(datetime_str, "%Y-%m-%d")
            except Exception as e:
                date_posted = datetime.today()
        else:
            date_posted = datetime.today()
        benefits_tag = job_card.find("span", class_="result-benefits__text")
        benefits = " ".join(benefits_tag.get_text().split()) if benefits_tag else None

        description, job_type = self.get_job_description(job_url)

        return JobPost(
            title=title,
            description=description,
            company_name=company,
            location=location,
            date_posted=int(date_posted.timestamp()) if date_posted else None,
            job_url=job_url,
            job_type=job_type,
            benefits=benefits,
            emails=extract_emails_from_text(description)
        )

    def get_job_description(self, job_page_url: str) -> tuple[None, None] | tuple[
        str | None, tuple[str | None, JobType | None]]:
        """
        Retrieves job description by going to the job page url
        :param job_page_url:
        :return: description or None
        """
        try:
            response = requests.get(job_page_url, timeout=15, proxies=self.proxy_config)
            time.sleep(1)
            response.raise_for_status()
        except Exception as e:
            return None, None

        soup = BeautifulSoup(response.text, "html.parser")
        div_content = soup.find(
            "div", class_=lambda x: x and "show-more-less-html__markup" in x
        )

        description = None
        if div_content:
            description = " ".join(div_content.get_text().split()).strip()

        def get_job_type(
                soup_job_type: BeautifulSoup,
        ) -> JobType | None:
            """
            Gets the job type from job page
            :param soup_job_type:
            :return: JobType
            """
            h3_tag = soup_job_type.find(
                "h3",
                class_="description__job-criteria-subheader",
                string=lambda text: "Employment type" in text,
            )

            employment_type = None
            if h3_tag:
                employment_type_span = h3_tag.find_next_sibling(
                    "span",
                    class_="description__job-criteria-text description__job-criteria-text--criteria",
                )
                if employment_type_span:
                    employment_type = employment_type_span.get_text(strip=True)
                    employment_type = employment_type.lower()
                    employment_type = employment_type.replace("-", "")

            return LinkedInScraper.get_enum_from_value(employment_type)

        return description, get_job_type(soup)

    @staticmethod
    def get_enum_from_value(value_str):
        for job_type in JobType:
            if value_str in job_type.value:
                return job_type
        return None

    def get_location(self, metadata_card: Optional[Tag]) -> Location:
        """
        Extracts the location data from the job metadata card.
        :param metadata_card
        :return: location
        """
        location = Location(country=self.country)
        if metadata_card is not None:
            location_tag = metadata_card.find(
                "span", class_="job-search-card__location"
            )
            location_string = location_tag.text.strip() if location_tag else "N/A"
            parts = location_string.split(", ")
            if len(parts) == 2:
                city, state = parts
                location = Location(
                    city=city,
                    state=state,
                    country=self.country,
                )

        return location

def extract_emails_from_text(text: str) -> Optional[list[str]]:
    if not text:
        return None
    email_regex = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    return email_regex.findall(text)