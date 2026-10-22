BOT_NAME = "daily_arxiv"

SPIDER_MODULES = ["daily_arxiv.spiders"]
NEWSPIDER_MODULE = "daily_arxiv.spiders"

ROBOTSTXT_OBEY = True

ITEM_PIPELINES = {
    "daily_arxiv.pipelines.DailyArxivPipeline": 300,
}

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"
