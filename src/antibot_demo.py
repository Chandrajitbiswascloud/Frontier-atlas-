import asyncio
import random
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]


async def fetch_rendered_page(url: str, proxy_url: str | None = None) -> str:
  """Asynchronously renders a JavaScript-heavy webpage using Playwright.

  Supports optional proxy routing, randomized browser profiles, and blocks
  heavy media assets to keep extraction fast and lightweight.
  """
  async with async_playwright() as p:
    launch_kwargs = {
        "headless": True,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    }
    if proxy_url:
      launch_kwargs["proxy"] = {"server": proxy_url}

    browser = await p.chromium.launch(**launch_kwargs)
    try:
      context = await browser.new_context(
          user_agent=random.choice(USER_AGENTS),
          viewport={
              "width": random.choice([1280, 1366, 1440, 1920]),
              "height": random.choice([720, 800, 900, 1080]),
          },
          locale="en-US",
          timezone_id="America/New_York",
      )

      # Mask standard webdriver flag
      await context.add_init_script(
          "Object.defineProperty(navigator, 'webdriver', {get: () =>"
          " undefined});"
      )

      page = await context.new_page()

      # Abort images, stylesheets, and fonts to reduce bandwidth and latency
      await page.route(
          "**/*",
          lambda route: route.abort()
          if route.request.resource_type in {"image", "media", "font"}
          else route.continue_(),
      )

      await page.goto(url, wait_until="domcontentloaded", timeout=25000)
      # Brief randomized human-like pause for dynamic JS hydration
      await asyncio.sleep(random.uniform(1.2, 2.5))

      html = await page.content()
      return html
    finally:
      await browser.close()


async def main():
  target = "https://www.ycombinator.com/companies"
  print(f"Rendering dynamic page asynchronously: {target}")
  html = await fetch_rendered_page(target)
  soup = BeautifulSoup(html, "html.parser")
  title = soup.title.string.strip() if soup.title else "No title"
  print(f"Successfully extracted DOM ({len(html)} bytes) | Title: {title}")


if __name__ == "__main__":
  asyncio.run(main())