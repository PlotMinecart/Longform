
import os
import json
import time
import queue
import base64
import threading
import webbrowser
import urllib.request
import urllib.parse
import urllib.error
import tkinter as tk

from pathlib import Path
from tkinter import ttk, messagebox
from datetime import datetime, timezone

# ==========================================
# PLOTMINECART - REDDIT LONG FORM
# Stage 1: Search, Select and Review
# ==========================================

BASE = Path(
    r"C:\Users\harri\Documents\Automated Youtube"
    r"\PlotMinecart_LongForm"
)

PLANS = BASE / "episode_plans"
PLANS.mkdir(parents=True, exist_ok=True)

CLIENT_ID = os.environ.get(
    "REDDIT_CLIENT_ID", ""
)

CLIENT_SECRET = os.environ.get(
    "REDDIT_CLIENT_SECRET", ""
)

USER_AGENT = (
    "windows:PlotMinecartLongForm:0.1 "
    "(approved personal Reddit research app)"
)

API_BASE = "https://oauth.reddit.com"

messages = queue.Queue()
posts = {}
review_ids = []
busy = False


# ==========================================
# REDDIT API
# ==========================================

def fetch_token():

    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError(
            "Reddit API credentials are missing. "
            "Configure REDDIT_CLIENT_ID and "
            "REDDIT_CLIENT_SECRET first."
        )

    credentials = base64.b64encode(
        f"{CLIENT_ID}:{CLIENT_SECRET}".encode()
    ).decode()

    request = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=urllib.parse.urlencode({
            "grant_type": "client_credentials"
        }).encode(),
        headers={
            "Authorization": f"Basic {credentials}",
            "User-Agent": USER_AGENT,
            "Content-Type":
                "application/x-www-form-urlencoded"
        },
        method="POST"
    )

    with urllib.request.urlopen(
        request, timeout=30
    ) as response:
        data = json.load(response)

    token = data.get("access_token")

    if not token:
        raise RuntimeError(
            "Reddit did not return an access token."
        )

    return token


def fetch_weekly_posts(subreddit):

    token = fetch_token()

    params = urllib.parse.urlencode({
        "t": "week",
        "limit": 100,
        "raw_json": 1
    })

    url = (
        f"{API_BASE}/r/{subreddit}/top.json?"
        f"{params}"
    )

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT
        }
    )

    with urllib.request.urlopen(
        request, timeout=30
    ) as response:
        data = json.load(response)

    cutoff = time.time() - 7 * 86400
    results = []

    for child in data.get(
        "data", {}
    ).get("children", []):

        item = child.get("data", {})

        if item.get("created_utc", 0) < cutoff:
            continue

        if item.get("over_18", False):
            continue

        if item.get("stickied", False):
            continue

        body = item.get("selftext", "")

        if body in ("[removed]", "[deleted]"):
            continue

        if item.get("removed_by_category"):
            continue

        post_id = item.get("id")

        if not post_id:
            continue

        results.append({
            "id": post_id,
            "title": item.get("title", ""),
            "body": body,
            "score": item.get("score", 0),
            "comments": item.get(
                "num_comments", 0
            ),
            "created": item.get(
                "created_utc", 0
            ),
            "url": (
                "https://www.reddit.com"
                + item.get("permalink", "")
            ),
            "subreddit": subreddit
        })

    results.sort(
        key=lambda p: (
            p["score"],
            p["comments"]
        ),
        reverse=True
    )

    return results


# ==========================================
# BACKGROUND SEARCH
# ==========================================

def search_posts():

    global busy

    if busy:
        return

    subreddit = subreddit_var.get().strip()

    if subreddit.lower().startswith("r/"):
        subreddit = subreddit[2:]

    if not subreddit:
        messagebox.showwarning(
            "Missing subreddit",
            "Enter a subreddit name."
        )
        return

    if not all(
        c.isalnum() or c == "_"
        for c in subreddit
    ):
        messagebox.showerror(
            "Invalid subreddit",
            "Use a subreddit name such as "
            "AmItheAsshole."
        )
        return

    busy = True
    search_button.config(state="disabled")
    status_var.set(
        f"Searching r/{subreddit}..."
    )

    def worker():
        try:
            result = fetch_weekly_posts(subreddit)
            messages.put(("results", result))
        except urllib.error.HTTPError as error:
            messages.put((
                "error",
                f"Reddit returned HTTP {error.code}. "
                "Check your API approval and credentials."
            ))
        except Exception as error:
            messages.put(("error", str(error)))

    threading.Thread(
        target=worker,
        daemon=True
    ).start()


def handle_messages():

    global busy
    global posts

    try:
        while True:
            kind, payload = messages.get_nowait()

            busy = False
            search_button.config(state="normal")

            if kind == "error":
                status_var.set("Search failed")
                messagebox.showerror(
                    "Reddit Search Error",
                    payload
                )
                continue

            posts = {
                p["id"]: p
                for p in payload
            }

            results_tree.delete(
                *results_tree.get_children()
            )

            for post in payload:

                date = datetime.fromtimestamp(
                    post["created"],
                    tz=timezone.utc
                ).strftime("%d %b")

                results_tree.insert(
                    "",
                    "end",
                    iid=post["id"],
                    values=(
                        post["score"],
                        post["comments"],
                        date,
                        post["title"]
                    )
                )

            status_var.set(
                f"Found {len(payload)} posts "
                "from the last seven days"
            )

    except queue.Empty:
        pass

    root.after(150, handle_messages)


# ==========================================
# POST PREVIEW
# ==========================================

def selected_post():

    selection = results_tree.selection()

    if not selection:
        return None

    return posts.get(selection[0])


def show_preview(event=None):

    post = selected_post()

    preview.config(state="normal")
    preview.delete("1.0", "end")

    if post:
        content = (
            post["title"]
            + "\n\n"
            + post["body"][:7000]
        )

        preview.insert("1.0", content)

    preview.config(state="disabled")


def open_post():

    post = selected_post()

    if post:
        webbrowser.open(post["url"])


# ==========================================
# EPISODE REVIEW QUEUE
# ==========================================

def add_to_review():

    selection = results_tree.selection()

    if not selection:
        messagebox.showwarning(
            "No selection",
            "Select one or more posts first."
        )
        return

    added = 0

    for post_id in selection:
        if (
            post_id in posts
            and post_id not in review_ids
        ):
            review_ids.append(post_id)
            added += 1

    update_review_list()

    status_var.set(
        f"Added {added} post(s) to review"
    )


def update_review_list():

    review_list.delete(0, "end")

    for post_id in review_ids:

        post = posts.get(post_id)

        if post:
            review_list.insert(
                "end",
                post["title"][:90]
            )


def remove_from_review():

    indices = list(
        review_list.curselection()
    )

    for index in reversed(indices):
        del review_ids[index]

    update_review_list()


def save_review_plan():

    if not review_ids:
        messagebox.showwarning(
            "Empty review",
            "Add at least one post."
        )
        return

    angle = angle_input.get(
        "1.0", "end"
    ).strip()

    if not angle:
        messagebox.showwarning(
            "Missing commentary plan",
            "Write how the episode will add "
            "original analysis or commentary."
        )
        return

    # Save links and creator notes, not
    # complete copies of Reddit stories.
    references = []

    for post_id in review_ids:

        post = posts.get(post_id)

        if not post:
            continue

        references.append({
            "url": post["url"],
            "rights_status": "Not verified",
            "permission_verified": False
        })

    plan = {
        "created_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "working_title": (
            episode_title.get().strip()
            or "Untitled Reddit discussion"
        ),
        "creator_commentary_plan": angle,
        "references": references,
        "production_status":
            "Pending rights and editorial review",
        "target_video_minutes": 10
    }

    name = datetime.now().strftime(
        "episode_%Y%m%d_%H%M%S_%f.json"
    )

    path = PLANS / name

    path.write_text(
        json.dumps(
            plan,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    messagebox.showinfo(
        "Review Plan Saved",
        f"Saved:\n{path}\n\n"
        "This is a draft review plan, "
        "not an authorisation to reuse posts."
    )


# ==========================================
# USER INTERFACE
# ==========================================

root = tk.Tk()
root.title("PlotMinecart — Reddit Long Form")
root.geometry("1150x790")
root.minsize(900, 680)
root.configure(bg="#171B27")

style = ttk.Style()
style.theme_use("clam")

style.configure(
    "Treeview",
    rowheight=28,
    font=("Segoe UI", 10)
)

style.configure(
    "Treeview.Heading",
    font=("Segoe UI", 10, "bold")
)

header = tk.Frame(root, bg="#171B27")
header.pack(fill="x", padx=18, pady=12)

tk.Label(
    header,
    text="PLOTMINECART — LONG FORM",
    font=("Segoe UI", 20, "bold"),
    fg="white",
    bg="#171B27"
).pack(anchor="w")

tk.Label(
    header,
    text="Reddit Story Finder & Episode Review",
    font=("Segoe UI", 10),
    fg="#B5BDCD",
    bg="#171B27"
).pack(anchor="w")

search_frame = tk.Frame(
    root, bg="#171B27"
)
search_frame.pack(fill="x", padx=18, pady=5)

tk.Label(
    search_frame,
    text="r/",
    font=("Segoe UI", 13, "bold"),
    fg="white",
    bg="#171B27"
).pack(side="left")

subreddit_var = tk.StringVar(
    value="AmItheAsshole"
)

subreddit_entry = ttk.Entry(
    search_frame,
    textvariable=subreddit_var,
    width=28
)
subreddit_entry.pack(
    side="left", padx=5
)

search_button = ttk.Button(
    search_frame,
    text="Find Top Posts — Last 7 Days",
    command=search_posts
)
search_button.pack(
    side="left", padx=10
)

status_var = tk.StringVar(
    value="Ready. Approved Reddit API access required."
)

tk.Label(
    root,
    textvariable=status_var,
    anchor="w",
    fg="#DBD2FF",
    bg="#171B27"
).pack(fill="x", padx=18, pady=5)

table_frame = ttk.Frame(root)
table_frame.pack(
    fill="both",
    expand=True,
    padx=18,
    pady=6
)

results_tree = ttk.Treeview(
    table_frame,
    columns=(
        "score",
        "comments",
        "date",
        "title"
    ),
    show="headings",
    selectmode="extended",
    height=9
)

for key, title, width in [
    ("score", "Upvotes", 85),
    ("comments", "Comments", 90),
    ("date", "Posted", 90),
    ("title", "Reddit Post", 700)
]:
    results_tree.heading(
        key, text=title
    )
    results_tree.column(
        key,
        width=width,
        stretch=(key == "title"),
        anchor=("w" if key == "title" else "center")
    )

scrollbar = ttk.Scrollbar(
    table_frame,
    orient="vertical",
    command=results_tree.yview
)

results_tree.configure(
    yscrollcommand=scrollbar.set
)

results_tree.pack(
    side="left",
    fill="both",
    expand=True
)
scrollbar.pack(
    side="right",
    fill="y"
)

results_tree.bind(
    "<<TreeviewSelect>>",
    show_preview
)

actions = ttk.Frame(root)
actions.pack(fill="x", padx=18, pady=6)

ttk.Button(
    actions,
    text="Open Original Reddit Post",
    command=open_post
).pack(side="left", padx=(0, 8))

ttk.Button(
    actions,
    text="Add Selected Posts to Review",
    command=add_to_review
).pack(side="left")

lower = ttk.Frame(root)
lower.pack(
    fill="both",
    expand=True,
    padx=18,
    pady=8
)

left = ttk.LabelFrame(
    lower,
    text="Post Preview"
)
left.pack(
    side="left",
    fill="both",
    expand=True,
    padx=(0, 8)
)

preview = tk.Text(
    left,
    wrap="word",
    font=("Segoe UI", 10),
    height=9
)
preview.pack(
    fill="both",
    expand=True,
    padx=6,
    pady=6
)
preview.config(state="disabled")

right = ttk.LabelFrame(
    lower,
    text="Episode Review Queue"
)
right.pack(
    side="right",
    fill="both",
    expand=True
)

review_list = tk.Listbox(
    right,
    height=6,
    font=("Segoe UI", 9)
)
review_list.pack(
    fill="both",
    expand=True,
    padx=6,
    pady=6
)

ttk.Button(
    right,
    text="Remove Selected",
    command=remove_from_review
).pack(anchor="w", padx=6, pady=3)

editor = ttk.LabelFrame(
    root,
    text="Your Original Episode Plan"
)
editor.pack(
    fill="x",
    padx=18,
    pady=(4, 10)
)

ttk.Label(
    editor,
    text="Working episode title:"
).pack(anchor="w", padx=8, pady=(5, 1))

episode_title = ttk.Entry(editor)
episode_title.pack(
    fill="x",
    padx=8,
    pady=2
)

ttk.Label(
    editor,
    text="Original commentary / analysis angle:"
).pack(anchor="w", padx=8, pady=(5, 1))

angle_input = tk.Text(
    editor,
    height=3,
    wrap="word"
)
angle_input.pack(
    fill="x",
    padx=8,
    pady=3
)

ttk.Button(
    editor,
    text="Save Episode Review Plan",
    command=save_review_plan
).pack(pady=8)

root.after(150, handle_messages)
root.mainloop()
