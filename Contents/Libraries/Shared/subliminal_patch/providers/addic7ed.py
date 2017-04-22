# coding=utf-8
import logging
import re
import subliminal
from random import randint

from subliminal.exceptions import TooManyRequests
from subliminal.providers.addic7ed import Addic7edProvider as _Addic7edProvider, Addic7edSubtitle, ParserBeautifulSoup, Language
from subliminal.cache import SHOW_EXPIRATION_TIME, region
from subliminal.utils import sanitize

logger = logging.getLogger(__name__)

#: Series header parsing regex
series_year_re = re.compile(r'^(?P<series>[ \w\'.:(),&!?-]+?)(?: \((?P<year>\d{4})\))?$')


class PatchedAddic7edSubtitle(Addic7edSubtitle):
    def __init__(self, language, hearing_impaired, page_link, series, season, episode, title, year, version,
                 download_link):
        super(PatchedAddic7edSubtitle, self).__init__(language, hearing_impaired, page_link, series, season, episode,
                                                      title, year, version, download_link)
        self.release_info = version

    def get_matches(self, video):
        matches = super(PatchedAddic7edSubtitle, self).get_matches(video)
        if not subliminal.score.episode_scores.get("addic7ed_boost"):
            return matches

        if {"series", "season", "episode", "year"}.issubset(matches) and "format" in matches:
            matches.add("addic7ed_boost")
            logger.info("Boosting Addic7ed subtitle by %s" % subliminal.score.episode_scores.get("addic7ed_boost"))
        return matches


class Addic7edProvider(_Addic7edProvider):
    USE_ADDICTED_RANDOM_AGENTS = False

    def __init__(self, username=None, password=None, use_random_agents=False):
        super(Addic7edProvider, self).__init__(username=username, password=password)
        self.USE_ADDICTED_RANDOM_AGENTS = use_random_agents

    def initialize(self):
        # patch: add optional user agent randomization
        super(Addic7edProvider, self).initialize()
        if self.USE_ADDICTED_RANDOM_AGENTS:
            from .utils import FIRST_THOUSAND_OR_SO_USER_AGENTS as AGENT_LIST
            logger.debug("addic7ed: using random user agents")
            self.session.headers['User-Agent'] = AGENT_LIST[randint(0, len(AGENT_LIST) - 1)]
            self.session.headers['Referer'] = self.server_url

    @region.cache_on_arguments(expiration_time=SHOW_EXPIRATION_TIME)
    def _get_show_ids(self):
        """Get the ``dict`` of show ids per series by querying the `shows.php` page.
        :return: show id per series, lower case and without quotes.
        :rtype: dict

        # patch: add punctuation cleaning
        """
        # get the show page
        logger.info('Getting show ids')
        r = self.session.get(self.server_url + 'shows.php', timeout=10)
        r.raise_for_status()
        soup = ParserBeautifulSoup(r.content, ['lxml', 'html.parser'])

        # populate the show ids
        show_ids = {}
        for show in soup.select('td.version > h3 > a[href^="/show/"]'):
            show_clean = sanitize(show.text)
            try:
                show_id = int(show['href'][6:])
            except ValueError:
                continue

            show_ids[show_clean] = show_id
            match = series_year_re.match(show_clean)
            if match and match.group(2) and match.group(1) not in show_ids:
                # year found, also add it without year
                show_ids[match.group(1)] = show_id

        logger.debug('Found %d show ids', len(show_ids))

        return show_ids

    @region.cache_on_arguments(expiration_time=SHOW_EXPIRATION_TIME)
    def _search_show_id(self, series, year=None):
        """Search the show id from the `series` and `year`.

        :param str series: series of the episode.
        :param year: year of the series, if any.
        :type year: int
        :return: the show id, if found.
        :rtype: int

        """
        # addic7ed doesn't support search with quotes
        series = series.replace('\'', ' ')

        # build the params
        series_year = '%s %d' % (series, year) if year is not None else series
        params = {'search': series_year, 'Submit': 'Search'}

        # make the search
        logger.info('Searching show ids with %r', params)
        r = self.session.get(self.server_url + 'search.php', params=params, timeout=10)
        r.raise_for_status()
        if r.status_code == 304:
            raise TooManyRequests()
        soup = ParserBeautifulSoup(r.content, ['lxml', 'html.parser'])

        # get the suggestion
        suggestion = soup.select('span.titulo > a[href^="/show/"]')
        if not suggestion:
            logger.warning('Show id not found: no suggestion')
            return None
        if not sanitize(suggestion[0].i.text.replace('\'', ' ')) == sanitize(series_year):
            logger.warning('Show id not found: suggestion does not match')
            return None
        show_id = int(suggestion[0]['href'][6:])
        logger.debug('Found show id %d', show_id)

        return show_id

    def query(self, series, season, year=None, country=None):
        # patch: fix logging
        # get the show id
        show_id = self.get_show_id(series, year, country)
        if show_id is None:
            logger.error('No show id found for %r (%r)', series, {'year': year, 'country': country})
            return []

        # get the page of the season of the show
        logger.info('Getting the page of show id %d, season %d', show_id, season)
        r = self.session.get(self.server_url + 'show/%d' % show_id, params={'season': season}, timeout=10)
        r.raise_for_status()
        if r.status_code == 304:
            raise TooManyRequests()
        soup = ParserBeautifulSoup(r.content, ['lxml', 'html.parser'])

        # loop over subtitle rows
        subtitles = []
        for row in soup.select('tr.epeven'):
            cells = row('td')

            # ignore incomplete subtitles
            status = cells[5].text
            if status != 'Completed':
                logger.debug('Ignoring subtitle with status %s', status)
                continue

            # read the item
            language = Language.fromaddic7ed(cells[3].text)
            hearing_impaired = bool(cells[6].text)
            page_link = self.server_url + cells[2].a['href'][1:]
            season = int(cells[0].text)
            episode = int(cells[1].text)
            title = cells[2].text
            version = cells[4].text
            download_link = cells[9].a['href'][1:]

            subtitle = PatchedAddic7edSubtitle(language, hearing_impaired, page_link, series, season, episode, title, year,
                                               version, download_link)
            logger.debug('Found subtitle %r', subtitle)
            subtitles.append(subtitle)

        return subtitles