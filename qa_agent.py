import os
import sys
import time
import json
import getpass
from datetime import datetime
from urllib.parse import urlparse, urljoin

# Check if playwright is installed
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except ImportError:
    print("=" * 70)
    print("[Error] Playwright is not installed.")
    print("Please install it and its browser engines by running:")
    print("  pip install playwright")
    print("  python -m playwright install chromium")
    print("=" * 70)
    sys.exit(1)

REPORT_DIR = "reports"
SCREENSHOT_DIR = os.path.join(REPORT_DIR, "screenshots")

# Ensure directories exist
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

class StepLog:
    """Represents a single log action inside a test case."""
    def __init__(self, description, screenshot_path=None, status="INFO", error_msg=None):
        self.timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.description = description
        self.screenshot_path = screenshot_path  # Relative path for HTML report
        self.status = status  # INFO, SUCCESS, WARNING, FAILED
        self.error_msg = error_msg

class TestCase:
    """Represents a specific validation task (e.g., Page Load, Responsive Layout)."""
    def __init__(self, id_str, name, description):
        self.id = id_str
        self.name = name
        self.description = description
        self.status = "PENDING"  # PASSED, FAILED
        self.steps = []
        self.duration_ms = 0

    def add_step(self, description, screenshot_path=None, status="INFO", error_msg=None):
        step = StepLog(description, screenshot_path, status, error_msg)
        self.steps.append(step)
        
        # Log to command line
        status_marker = f"[{status}]"
        print(f"    {status_marker:<9} {description}")
        if error_msg:
            print(f"      Error: {error_msg}")
        return step

class PageRouteTest:
    """Represents the complete test suite run on a single URL path/route."""
    def __init__(self, url, path_name, index):
        self.url = url
        self.path_name = path_name
        self.index = index
        self.title = ""
        self.test_suite = []
        
    def add_test(self, id_str, name, description):
        test = TestCase(id_str, name, description)
        self.test_suite.append(test)
        return test
        
    @property
    def status(self):
        """If any test in the suite failed, the page audit is marked as FAILED."""
        if any(t.status == "FAILED" for t in self.test_suite):
            return "FAILED"
        if all(t.status == "PASSED" for t in self.test_suite):
            return "PASSED"
        return "PENDING"

class QAAgent:
    def __init__(self, target_url, max_pages=10):
        self.target_url = target_url
        self.parsed_origin = urlparse(target_url)
        self.origin = f"{self.parsed_origin.scheme}://{self.parsed_origin.netloc}"
        self.max_pages = max_pages
        
        self.username = None
        self.password = None
        
        # Crawling queue and visited sets
        self.routes_to_visit = []
        self.visited_urls = set()
        self.pages_tested = []  # List of PageRouteTest objects
        
        # Global console log aggregation
        self.console_logs_by_url = {}  # url -> list of logs
        self.page_errors_by_url = {}   # url -> list of exceptions

    def prompt_credentials_if_needed(self):
        """Pre-scans the target page to see if a password field is present.
        If found, requests credentials from the CLI."""
        print(f"\n[System] Pre-scanning {self.target_url} for authorization forms...")
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            try:
                page.goto(self.target_url, timeout=10000)
                password_field = page.query_selector('input[type="password"]')
                if password_field:
                    print("\n" + "*" * 60)
                    print("[Auth] SECURE AUTHENTICATION DETECTED")
                    print("   This site contains a password field. Please enter credentials:")
                    print("*" * 60)
                    self.username = input("Username / Email: ").strip()
                    self.password = getpass.getpass("Password: ")
                    print("Credentials stored in memory for authentication.\n")
                else:
                    print("[System] No password inputs detected on landing page. Running unauthenticated tests.")
            except Exception as e:
                print(f"[Warning] Failed to complete pre-scan: {e}. Proceeding without credentials.")
            finally:
                browser.close()

    def run_tests(self):
        self.prompt_credentials_if_needed()
        
        print("\n" + "=" * 60)
        print("                 STARTING DEEP QA CRAWL RUN")
        print("=" * 60)
        
        with sync_playwright() as p:
            # We launch headless=False so the user can visually see the agent navigating
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            
            # Global handlers for logs
            def on_console(msg, current_url):
                if current_url not in self.console_logs_by_url:
                    self.console_logs_by_url[current_url] = []
                self.console_logs_by_url[current_url].append(f"[{msg.type.upper()}] {msg.text}")
                
            def on_pageerror(err, current_url):
                if current_url not in self.page_errors_by_url:
                    self.page_errors_by_url[current_url] = []
                self.page_errors_by_url[current_url].append(err.message)

            page.on("console", lambda msg: on_console(msg, page.url))
            page.on("pageerror", lambda err: on_pageerror(err, page.url))

            # 1. Perform Authentication/Login if required
            try:
                print(f"\n[Step 1] Accessing entry URL: {self.target_url}")
                page.goto(self.target_url, timeout=15000)
                page.wait_for_timeout(1000)
                
                if self.username and self.password:
                    user_input = page.query_selector('input[type="email"], input[type="text"][name*="user"], input[type="text"][placeholder*="user"], input[placeholder*="username"], input[name*="username"]')
                    pass_input = page.query_selector('input[type="password"]')
                    submit_btn = page.query_selector('button[type="submit"], input[type="submit"], button:has-text("Login"), button:has-text("Sign In")')
                    
                    if user_input and pass_input:
                        print("[Auth] Logging in using provided credentials...")
                        user_input.fill(self.username)
                        pass_input.fill(self.password)
                        
                        # Take pre-submit screenshot
                        os.makedirs(os.path.join(SCREENSHOT_DIR, "page_0_auth"), exist_ok=True)
                        page.screenshot(path=os.path.join(SCREENSHOT_DIR, "page_0_auth", "auth_filled.png"))
                        
                        if submit_btn:
                            submit_btn.click()
                            page.wait_for_timeout(4000)  # Wait for auth redirect
                            print(f"Logged in successfully. Current landing URL: {page.url}")
                        else:
                            print("[Error] Submit button not found.")
                    else:
                        print("[Warning] Login input elements not found on page load.")
            except Exception as e:
                print(f"[Critical] Failed to establish initial load or authentication: {e}")
                browser.close()
                return

            # Determine starting point for crawl queue
            start_url = page.url
            self.routes_to_visit.append(start_url)
            page_index = 1
            
            # Start Crawling Loop
            while self.routes_to_visit and len(self.visited_urls) < self.max_pages:
                current_url = self.routes_to_visit.pop(0)
                
                # Normalize URL (strip query/hash)
                parsed_url = urlparse(current_url)
                normalized_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
                
                if normalized_url in self.visited_urls:
                    continue
                    
                self.visited_urls.add(normalized_url)
                
                path_display = parsed_url.path or "/"
                print(f"\n" + "-" * 60)
                print(f"PAGE {page_index}: Auditing route {path_display}")
                print(f"   Full URL: {current_url}")
                print("-" * 60)
                
                # Create PageRoute object
                route_test = PageRouteTest(current_url, path_display, page_index)
                self.pages_tested.append(route_test)
                
                # Setup page directories
                page_ss_dir = f"page_{page_index}"
                os.makedirs(os.path.join(SCREENSHOT_DIR, page_ss_dir), exist_ok=True)
                
                # Run the individual test suite on this page
                self.audit_single_page(page, route_test, page_ss_dir)
                
                # Discover new links on this page
                new_links = self.discover_internal_links(page)
                for link in new_links:
                    parsed_link = urlparse(link)
                    norm_link = f"{parsed_link.scheme}://{parsed_link.netloc}{parsed_link.path}"
                    if norm_link not in self.visited_urls and link not in self.routes_to_visit:
                        self.routes_to_visit.append(link)
                
                page_index += 1
                
            browser.close()
            
        # Write HTML Report
        self.generate_html_report()

    def audit_single_page(self, page, route_test, page_ss_dir):
        """Performs Page Load, Console checks, Viewport renders, and Interactivity tests on the current page."""
        t1 = route_test.add_test("T1_LOAD", "Load Health Check", "Verifies page loads cleanly with 2xx status code.")
        t2 = route_test.add_test("T2_CONSOLE", "Console Log Audit", "Checks console for script errors.")
        t3 = route_test.add_test("T3_RESPONSIVE", "Responsive Viewports Check", "Captures layout outputs on Desktop and Mobile sizes.")
        t4 = route_test.add_test("T4_INTERACTIVITY", "Interaction Test", "Simulates user navigation/tabs clicks, checking for exceptions.")

        # -------------------------------------------------------------
        # T1: PAGE LOAD
        # -------------------------------------------------------------
        print(f"  [Test] {t1.name}...")
        start_time = time.time()
        try:
            # We are already on the page or we navigate to it to ensure fresh load
            if page.url != route_test.url:
                response = page.goto(route_test.url, timeout=12000)
                status_code = response.status if response else 200
            else:
                status_code = 200 # Current active page
            
            load_time = (time.time() - start_time) * 1000
            t1.duration_ms = load_time
            route_test.title = page.title() or route_test.path_name
            
            if 200 <= status_code < 400:
                t1.add_step(f"Page resolved in {load_time:.0f}ms with status {status_code}", status="SUCCESS")
                
                # Screenshot
                ss_rel_path = f"screenshots/{page_ss_dir}/load_success.png"
                page.screenshot(path=os.path.join(SCREENSHOT_DIR, page_ss_dir, "load_success.png"))
                t1.add_step("Captured route landing screenshot", screenshot_path=ss_rel_path)
                t1.status = "PASSED"
            else:
                t1.add_step(f"Unhealthy status returned: {status_code}", status="FAILED")
                t1.status = "FAILED"
        except Exception as e:
            t1.add_step("Failed page navigation", status="FAILED", error_msg=str(e))
            t1.status = "FAILED"

        # -------------------------------------------------------------
        # T2: CONSOLE LOG AUDIT
        # -------------------------------------------------------------
        print(f"  [Test] {t2.name}...")
        t2_start = time.time()
        page.wait_for_timeout(1000) # Wait for page scripts
        
        url = page.url
        console_logs = self.console_logs_by_url.get(url, [])
        page_errors = self.page_errors_by_url.get(url, [])
        
        # Log recent entries
        for log in console_logs[-6:]:
            t2.add_step(f"Console log: {log}", status="INFO")
            
        error_count = len(page_errors)
        if error_count > 0:
            t2.add_step(f"Found {error_count} critical JS exceptions on page console.", status="WARNING")
            for err in page_errors:
                t2.add_step(f"JS Exception: {err}", status="FAILED")
            t2.status = "FAILED"
        else:
            t2.add_step("No critical JS exceptions detected.", status="SUCCESS")
            t2.status = "PASSED"
        t2.duration_ms = (time.time() - t2_start) * 1000

        # -------------------------------------------------------------
        # T3: RESPONSIVE CHECK
        # -------------------------------------------------------------
        print(f"  [Test] {t3.name}...")
        t3_start = time.time()
        try:
            # Desktop viewport
            page.set_viewport_size({"width": 1280, "height": 800})
            page.wait_for_timeout(500)
            desktop_ss = f"screenshots/{page_ss_dir}/layout_desktop.png"
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, page_ss_dir, "layout_desktop.png"))
            t3.add_step("Desktop view rendering verified", screenshot_path=desktop_ss, status="SUCCESS")
            
            # Mobile viewport
            page.set_viewport_size({"width": 375, "height": 812})
            page.wait_for_timeout(500)
            mobile_ss = f"screenshots/{page_ss_dir}/layout_mobile.png"
            page.screenshot(path=os.path.join(SCREENSHOT_DIR, page_ss_dir, "layout_mobile.png"))
            t3.add_step("Mobile view rendering verified", screenshot_path=mobile_ss, status="SUCCESS")
            
            # Reset Desktop standard
            page.set_viewport_size({"width": 1280, "height": 800})
            t3.status = "PASSED"
        except Exception as e:
            t3.add_step("Resizing layouts failed", status="FAILED", error_msg=str(e))
            t3.status = "FAILED"
        t3.duration_ms = (time.time() - t3_start) * 1000

        # -------------------------------------------------------------
        # T4: INTERACTIVE ELEMENTS TEST
        # -------------------------------------------------------------
        print(f"  [Test] {t4.name}...")
        t4_start = time.time()
        try:
            # Gather buttons/navigation items/tabs on page
            interactives = page.query_selector_all("button, a.nav-link, a.tab, [role='tab'], [role='button'], nav a")
            
            # Excluded keywords to avoid logging out or deleting data
            skip_keywords = ["delete", "remove", "logout", "signout", "exit", "reset", "clear", "cancel"]
            
            valid_targets = []
            for item in interactives:
                try:
                    if not item.is_visible():
                        continue
                    text = (item.text_content() or "").strip().lower()
                    if any(kw in text for kw in skip_keywords):
                        continue
                    valid_targets.append(item)
                except Exception:
                    continue
            
            targets_to_test = valid_targets[:3]  # Test up to 3 interactive items
            t4.add_step(f"Scanned page. Found {len(valid_targets)} potential interactive elements. Clicking top {len(targets_to_test)}.")
            
            click_failures = 0
            for idx, el in enumerate(targets_to_test):
                try:
                    text_label = (el.text_content() or f"element_{idx}").strip()
                    t4.add_step(f"Simulating click on: '{text_label}'")
                    
                    # Take before screenshot
                    before_ss = f"screenshots/{page_ss_dir}/click_{idx}_before.png"
                    el.screenshot(path=os.path.join(SCREENSHOT_DIR, page_ss_dir, f"click_{idx}_before.png"))
                    
                    # Click element
                    el.click()
                    page.wait_for_timeout(1000)  # Wait for AJAX/transitions
                    
                    # Take after screenshot
                    after_ss = f"screenshots/{page_ss_dir}/click_{idx}_after.png"
                    page.screenshot(path=os.path.join(SCREENSHOT_DIR, page_ss_dir, f"click_{idx}_after.png"))
                    t4.add_step(f"Successfully clicked '{text_label}'", screenshot_path=after_ss, status="SUCCESS")
                    
                    # Check console for new errors post click
                    errors_post_click = self.page_errors_by_url.get(page.url, [])
                    if len(errors_post_click) > len(page_errors):
                        t4.add_step(f"Clicking '{text_label}' triggered a new console script error!", status="FAILED")
                        click_failures += 1
                        
                    # If we navigated away, go back to restore page state for next clicks
                    if page.url != route_test.url:
                        t4.add_step("Click caused navigation. Returning to target path...")
                        page.go_back()
                        page.wait_for_timeout(1000)
                except Exception as click_err:
                    t4.add_step(f"Click execution failed for item {idx}", status="WARNING", error_msg=str(click_err))
            
            if click_failures > 0:
                t4.status = "FAILED"
            else:
                t4.add_step("All interactive elements executed without console exceptions.", status="SUCCESS")
                t4.status = "PASSED"
        except Exception as e:
            t4.add_step("Failed interactive sweep", status="FAILED", error_msg=str(e))
            t4.status = "FAILED"
        t4.duration_ms = (time.time() - t4_start) * 1000

    def discover_internal_links(self, page):
        """Scans page for anchor elements and filters for local same-origin routes."""
        discovered = []
        try:
            anchors = page.query_selector_all("a")
            for a in anchors:
                href = a.get_attribute("href")
                if not href:
                    continue
                # Skip hash routing or javascript
                if href.startswith("#") or href.startswith("javascript:"):
                    continue
                    
                # Resolve absolute
                absolute_url = page.evaluate("href => new URL(href, window.location.href).href", href)
                parsed = urlparse(absolute_url)
                
                # Check origin (same protocol + host)
                link_origin = f"{parsed.scheme}://{parsed.netloc}"
                if link_origin == self.origin:
                    # Filter out logout URLs
                    path_lower = parsed.path.lower()
                    if not any(kw in path_lower for kw in ["logout", "signout", "exit"]):
                        discovered.append(absolute_url)
        except Exception:
            pass
        return list(set(discovered))

    def generate_html_report(self):
        """Compiles route-level metrics and timelines into reports/qa_report.html."""
        report_path = os.path.join(REPORT_DIR, "qa_report.html")
        
        # Calculate stats
        total_routes = len(self.pages_tested)
        passed_routes = sum(1 for p in self.pages_tested if p.status == "PASSED")
        failed_routes = sum(1 for p in self.pages_tested if p.status == "FAILED")
        
        total_duration = 0
        total_test_cases = 0
        passed_test_cases = 0
        failed_test_cases = 0
        
        for r in self.pages_tested:
            total_duration += sum(t.duration_ms for t in r.test_suite)
            for t in r.test_suite:
                total_test_cases += 1
                if t.status == "PASSED":
                    passed_test_cases += 1
                else:
                    failed_test_cases += 1

        html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Deep QA Agent Audit Report</title>
    <style>
        :root {{
            --bg-color: #0b0c10;
            --card-bg: #1f2833;
            --border-color: #45a29e;
            --accent-purple: #bb86fc;
            --accent-green: #66fcf1;
            --accent-red: #ff0055;
            --accent-orange: #ffb703;
            --text-primary: #ffffff;
            --text-secondary: #c5c6c7;
        }}
        body {{
            background-color: var(--bg-color);
            color: var(--text-primary);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 24px;
        }}
        .container {{
            max-width: 1100px;
            margin: 0 auto;
        }}
        header {{
            margin-bottom: 32px;
            border-bottom: 1px solid rgba(69, 162, 158, 0.3);
            padding-bottom: 20px;
        }}
        h1 {{
            margin: 0 0 8px 0;
            font-size: 28px;
            color: var(--accent-green);
            font-weight: 700;
        }}
        .target-url {{
            color: var(--text-secondary);
            font-size: 14px;
        }}
        
        /* Stats Dashboard */
        .dashboard {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 32px;
        }}
        .stat-card {{
            background-color: var(--card-bg);
            border: 1px solid rgba(69, 162, 158, 0.2);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        .stat-value {{
            font-size: 28px;
            font-weight: 700;
            margin-top: 4px;
        }}
        .stat-label {{
            font-size: 11px;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.1em;
        }}
        .stat-passed {{ color: var(--accent-green); }}
        .stat-failed {{ color: var(--accent-red); }}
        
        /* Filters */
        .filters {{
            display: flex;
            gap: 10px;
            margin-bottom: 24px;
        }}
        .filter-btn {{
            background-color: var(--card-bg);
            border: 1px solid rgba(69, 162, 158, 0.2);
            color: var(--text-primary);
            padding: 10px 20px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .filter-btn:hover {{
            border-color: var(--accent-green);
        }}
        .filter-btn.active {{
            background-color: var(--accent-green);
            border-color: var(--accent-green);
            color: #0b0c10;
        }}
        
        /* Route Items */
        .route-list {{
            display: flex;
            flex-direction: column;
            gap: 20px;
        }}
        .route-card {{
            background-color: var(--card-bg);
            border: 1px solid rgba(69, 162, 158, 0.15);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 4px 10px rgba(0,0,0,0.15);
        }}
        .route-header {{
            padding: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            background-color: rgba(255,255,255,0.02);
            border-bottom: 1px solid transparent;
        }}
        .route-header:hover {{
            background-color: rgba(255,255,255,0.04);
        }}
        .route-header.active {{
            border-bottom-color: rgba(69, 162, 158, 0.2);
        }}
        .route-title {{
            display: flex;
            flex-direction: column;
            gap: 4px;
        }}
        .route-path {{
            font-weight: 700;
            font-size: 18px;
            color: var(--accent-purple);
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .route-page-title {{
            font-size: 12px;
            color: var(--text-secondary);
        }}
        
        .badge {{
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
        }}
        .badge-passed {{
            background-color: rgba(102, 252, 241, 0.1);
            color: var(--accent-green);
            border: 1px solid rgba(102, 252, 241, 0.3);
        }}
        .badge-failed {{
            background-color: rgba(255, 0, 85, 0.1);
            color: var(--accent-red);
            border: 1px solid rgba(255, 0, 85, 0.3);
        }}
        
        .route-content {{
            display: none;
            padding: 24px;
            background-color: rgba(0,0,0,0.15);
        }}
        
        /* Inner Test Case Box */
        .test-box {{
            border: 1px solid rgba(69, 162, 158, 0.1);
            border-radius: 8px;
            margin-bottom: 16px;
            background-color: rgba(255,255,255,0.01);
            overflow: hidden;
        }}
        .test-box-header {{
            padding: 12px 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            background-color: rgba(255,255,255,0.02);
            font-size: 14px;
            font-weight: 600;
            border-bottom: 1px solid rgba(69, 162, 158, 0.1);
        }}
        
        /* Steps Table */
        .steps-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}
        .steps-table th, .steps-table td {{
            padding: 10px 14px;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }}
        .steps-table th {{
            color: var(--text-secondary);
            font-size: 11px;
            text-transform: uppercase;
            font-weight: 700;
        }}
        .row-success {{ color: #d1fae5; }}
        .row-failed {{ color: #fee2e2; background-color: rgba(255,0,85,0.02); }}
        .row-warning {{ color: #fef3c7; }}
        
        .indicator-dot {{
            width: 6px;
            height: 6px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 6px;
        }}
        .dot-success {{ background-color: var(--accent-green); }}
        .dot-failed {{ background-color: var(--accent-red); }}
        .dot-warning {{ background-color: var(--accent-orange); }}
        .dot-info {{ background-color: var(--text-secondary); }}
        
        /* Screenshots */
        .ss-thumbnail {{
            max-width: 120px;
            border-radius: 4px;
            border: 1px solid rgba(255,255,255,0.1);
            cursor: pointer;
            transition: transform 0.2s, border-color 0.2s;
        }}
        .ss-thumbnail:hover {{
            transform: scale(1.05);
            border-color: var(--accent-green);
        }}
        
        /* Modal Overlay */
        .modal {{
            display: none;
            position: fixed;
            z-index: 1000;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.9);
            justify-content: center;
            align-items: center;
        }}
        .modal-content {{
            max-width: 90%;
            max-height: 90%;
            border-radius: 8px;
            border: 2px solid rgba(69, 162, 158, 0.3);
        }}
        .modal-close {{
            position: absolute;
            top: 20px;
            right: 30px;
            color: white;
            font-size: 30px;
            font-weight: bold;
            cursor: pointer;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🤖 Deep QA Agent Crawler Report</h1>
            <div class="target-url">Crawl Domain origin: <a href="{self.target_url}" target="_blank" style="color:var(--accent-green);text-decoration:none;">{self.origin}</a></div>
            <div style="font-size:12px;color:var(--text-secondary);margin-top:4px;">Report Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
        </header>
        
        <div class="dashboard">
            <div class="stat-card">
                <div class="stat-label">Routes Crawled</div>
                <div class="stat-value">{total_routes}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Passed Pages</div>
                <div class="stat-value stat-passed">{passed_routes}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Failed Pages</div>
                <div class="stat-value stat-failed">{failed_routes}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Duration</div>
                <div class="stat-value">{total_duration/1000:.2f}s</div>
            </div>
        </div>
        
        <div class="filters">
            <button class="filter-btn active" onclick="filterPages('all')">All Pages ({total_routes})</button>
            <button class="filter-btn" onclick="filterPages('PASSED')">Passed ({passed_routes})</button>
            <button class="filter-btn" onclick="filterPages('FAILED')">Failed ({failed_routes})</button>
        </div>
        
        <div class="route-list">
        """
        
        for route in self.pages_tested:
            badge_class = f"badge-{route.status.lower()}"
            html_template += f"""
            <div class="route-card" data-status="{route.status}">
                <div class="route-header" id="header-{route.index}" onclick="toggleRoute('{route.index}')">
                    <div class="route-title">
                        <div class="route-path">
                            <span style="color:var(--text-secondary);font-size:14px;font-family:monospace;">#{route.index}</span>
                            {route.path_name}
                        </div>
                        <div class="route-page-title">Page Title: "{route.title}" | Target: {route.url}</div>
                    </div>
                    <div style="display:flex;align-items:center;gap:16px;">
                        <span class="badge {badge_class}">{route.status}</span>
                    </div>
                </div>
                <div class="route-content" id="content-{route.index}">
            """
            
            # Print Test Cases inside Route Content
            for test in route.test_suite:
                test_badge = "PASSED" if test.status == "PASSED" else "FAILED"
                test_badge_class = f"badge-{test_badge.lower()}"
                
                html_template += f"""
                    <div class="test-box">
                        <div class="test-box-header">
                            <div>
                                <span style="color:var(--accent-green);font-family:monospace;">[{test.id}]</span>
                                {test.name}
                                <span style="font-size:11px;color:var(--text-secondary);font-weight:normal;margin-left:8px;">{test.description}</span>
                            </div>
                            <div style="display:flex;align-items:center;gap:12px;">
                                <span style="font-size:11px;color:var(--text-secondary);font-weight:normal;">{test.duration_ms/1000:.2f}s</span>
                                <span class="badge {test_badge_class}" style="padding:2px 8px;font-size:10px;">{test_badge}</span>
                            </div>
                        </div>
                        <table class="steps-table">
                            <thead>
                                <tr>
                                    <th style="width:12%;">Timestamp</th>
                                    <th style="width:15%;">Status</th>
                                    <th style="width:53%;">Log Action Details</th>
                                    <th style="width:20%;">Screenshot Check</th>
                                </tr>
                            </thead>
                            <tbody>
                """
                
                for step in test.steps:
                    row_class = ""
                    dot_class = "dot-info"
                    if step.status == "SUCCESS":
                        row_class = "row-success"
                        dot_class = "dot-success"
                    elif step.status == "FAILED":
                        row_class = "row-failed"
                        dot_class = "dot-failed"
                    elif step.status == "WARNING":
                        row_class = "row-warning"
                        dot_class = "dot-warning"
                        
                    thumbnail_html = ""
                    if step.screenshot_path:
                        thumbnail_html = f'<img class="ss-thumbnail" src="{step.screenshot_path}" onclick="openModal(\'{step.screenshot_path}\', event)" alt="Step screenshot"/>'
                        
                    html_template += f"""
                                <tr class="{row_class}">
                                    <td style="font-family:monospace;font-size:11px;">{step.timestamp}</td>
                                    <td>
                                        <span class="indicator-dot {dot_class}"></span>
                                        {step.status}
                                    </td>
                                    <td>
                                        {step.description}
                                        {f'<div style="font-size:11px;color:var(--accent-red);margin-top:4px;font-family:monospace;">{step.error_msg}</div>' if step.error_msg else ""}
                                    </td>
                                    <td>{thumbnail_html}</td>
                                </tr>
                    """
                    
                html_template += """
                            </tbody>
                        </table>
                    </div>
                """
                
            html_template += """
                </div>
            </div>
            """
            
        html_template += """
        </div>
    </div>
    
    <!-- Image Modal Overlay -->
    <div id="imageModal" class="modal" onclick="closeModal()">
        <span class="modal-close" onclick="closeModal()">&times;</span>
        <img class="modal-content" id="modalImage">
    </div>
    
    <script>
        function toggleRoute(index) {
            const content = document.getElementById('content-' + index);
            const header = document.getElementById('header-' + index);
            if (content.style.display === 'block') {
                content.style.display = 'none';
                header.classList.remove('active');
            } else {
                content.style.display = 'block';
                header.classList.add('active');
            }
        }
        
        function filterPages(status) {
            // Update active button state
            const buttons = document.querySelectorAll('.filter-btn');
            buttons.forEach(btn => btn.classList.remove('active'));
            event.currentTarget.classList.add('active');
            
            // Filter route cards
            const cards = document.querySelectorAll('.route-card');
            cards.forEach(card => {
                if (status === 'all' || card.getAttribute('data-status') === status) {
                    card.style.display = 'block';
                } else {
                    card.style.display = 'none';
                }
            });
        }
        
        function openModal(src, event) {
            event.stopPropagation(); // Avoid collapsing details
            const modal = document.getElementById('imageModal');
            const modalImg = document.getElementById('modalImage');
            modal.style.display = 'flex';
            modalImg.src = src;
        }
        
        function closeModal() {
            document.getElementById('imageModal').style.display = 'none';
        }
    </script>
</body>
</html>
"""
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html_template)
            
        print("\n" + "=" * 60)
        print("                 DEEP QA REPORT COMPILED")
        print("=" * 60)
        print(f"Report generated: {os.path.abspath(report_path)}")
        print(f"Screenshots directory: {os.path.abspath(SCREENSHOT_DIR)}")
        print("=" * 60 + "\n")

def main():
    print("=" * 60)
    print("           AUTOMATED DEEP QA TESTING AGENT")
    print("=" * 60)
    
    url = input("Enter Target Website URL (e.g. https://example.com): ").strip()
    if not url:
        print("[Error] No URL provided. Exiting.")
        sys.exit(1)
        
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "http://" + url
        
    # We can default to max 10 pages, or ask the user
    max_pages_input = input("Enter maximum page crawling limit (default: 10): ").strip()
    max_pages = 10
    if max_pages_input.isdigit():
        max_pages = int(max_pages_input)
        
    agent = QAAgent(url, max_pages=max_pages)
    agent.run_tests()

if __name__ == "__main__":
    main()
