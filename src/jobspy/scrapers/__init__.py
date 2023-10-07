from ..jobs import Enum, BaseModel, JobType, JobResponse, Country
from typing import List, Optional, Any
import requests

class Site(Enum):
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    ZIP_RECRUITER = "zip_recruiter"


class ScraperInput(BaseModel):
    site_type: List[Site]
    search_term: str

    location: str = None
    country: Optional[Country] = Country.USA
    distance: Optional[int] = None
    is_remote: bool = False
    job_type: Optional[JobType] = None
    easy_apply: bool = None  # linkedin
    offset: int = 0

    results_wanted: int = 15


class Scraper:
    def __init__(self, site: Site, proxy: Optional[List[str]] = None):
        self.site = site
        self.proxy = proxy
        self.debug = False
        if self.debug:
            self.linkedin_cookie_file = '/home/fred/workspace/jobs/jobs/app1/chrome_profile/cookies.pkl'
            self.check_exist_url = 'http://127.0.0.1:8000/check_url'
        else:
            self.linkedin_cookie_file = '/home/centos/fred/jobs/app1/chrome_profile/cookies.pkl'
            self.check_exist_url = 'http://127.0.0.1:3040/check_url'



    def check_exist(self, job_url: str):
        try:
            response = requests.post(self.check_exist_url,{'job_url': job_url},timeout=20)
            if response.status_code == 200:
                return True
            elif response.status_code == 404:
                return False
            else:
                print(f'check job exist failed: {response.status_code}')
                return True
        except:
            return True
        
    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        ...
