from bs4 import BeautifulSoup

from src.sources.ptt_stock import _parse_pttweb_containers, _title_matches


SAMPLE = """
<html><body>
<div class="e7-container">
  <div class="e7-left">
    <div class="e7-recommendScore">31</div>
  </div>
  <div class="e7-right">
    <a class="e7-article-default" href="/bbs/Stock/M.1786122252.A.3F8">
      <span class="e7-title">
        <span class="e7-show-if-device-is-not-xs"><span>[標的] 2344華邦電/討論</span></span>
      </span>
    </a>
    <div><span>ShaoJi 20小時前 , 08/08</span></div>
  </div>
</div>
<div class="e7-container">
  <div class="e7-left">
    <div class="e7-recommendScore">6</div>
  </div>
  <div class="e7-right">
    <a class="e7-article-default" href="/bbs/Stock/M.1786131144.A.1B5">
      <span class="e7-title">
        <span class="e7-show-if-device-is-not-xs"><span>[標的] 3037欣興/討論</span></span>
      </span>
    </a>
  </div>
</div>
</body></html>
"""


def test_parse_pttweb_containers():
    posts = _parse_pttweb_containers(BeautifulSoup(SAMPLE, "lxml"))
    assert len(posts) == 2
    assert posts[0]["post_id"] == "M.1786122252.A.3F8"
    assert posts[0]["push_count"] == 31
    assert "華邦電" in posts[0]["title"]
    assert posts[1]["push_count"] == 6


def test_title_matches_code_and_alias():
    assert _title_matches("[標的] 2330 台積電", ["台積電", "2330"])
    assert _title_matches("國巨從1200元狂瀉", ["國巨", "2327"])
    assert not _title_matches("今天天氣好", ["台積電", "2330"])
