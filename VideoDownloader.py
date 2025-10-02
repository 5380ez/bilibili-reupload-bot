import os
import sqlite3
import yt_dlp
import time
import subprocess
import yaml

#自定义参数
UID = 145709539   #up主uid
VIDEO_NUMBER = 3  #批量下载视频数

UP_SPACE_URL = f"https://space.bilibili.com/{UID}/video"
DB_PATH = "mydb.db"
DOWNLOAD_DIR = f"./downloads/{UID}"
CONFIG_PATH = "config.yaml"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""create table if not exists videos (
                        id text primary key,
                        title text,
                        downloaded_at integer,
                        status text
                    )""")
    conn.commit()
    return conn

def get_status_dict(conn):
    cur = conn.cursor()
    cur.execute("select id, status from videos")
    return {row[0]: row[1] for row in cur.fetchall()}

def save_video_record(conn, vid, title, status="online"):
    cur = conn.cursor()
    cur.execute("insert or replace into videos (id, title, downloaded_at, status) values (?,?,?,?)",
                (vid, title, int(time.time()), status))
    conn.commit()

def download_new_videos():
    """检查并下载新视频，保存为 online"""
    conn = init_db()
    status_dict = get_status_dict(conn)

    def hook(d):
        if d['status'] == 'finished':
            info = d['info_dict']
            vid = info.get('id')
            title = info.get('title')
            print(f"✅ 下载完成: {title} ({vid})")
            save_video_record(conn, vid, title, status="online")

    ydl_opts = {
        "outtmpl": f"{DOWNLOAD_DIR}/%(title)s [%(id)s].%(ext)s",
        "merge_output_format": "mp4",
        "playlistend": VIDEO_NUMBER,
        "progress_hooks": [hook],
        "cookiefile": "cookies.txt",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        playlist_dict = ydl.extract_info(f"https://space.bilibili.com/{UID}/video", download=False)
        entries = playlist_dict.get("entries", [])

        online_ids = {e.get("id") for e in entries}

        # 标记消失的视频
        for vid, status in status_dict.items():
            if status == "online" and vid not in online_ids:
                cur = conn.cursor()
                cur.execute("update videos set status='deleted' where id=?", (vid,))
                conn.commit()
                print(f"⚠️ 视频已下架，标记为 deleted: {vid}")

        # 下载新视频
        to_download = []
        for e in entries:
            vid = e.get("id")
            if vid not in status_dict:  # 新视频
                to_download.append(f"https://www.bilibili.com/video/{vid}")

        if not to_download:
            print("😴 没有新视频。")
        else:
            print(f"🚀 准备下载 {len(to_download)} 个新视频...")
            ydl.download(to_download)


def build_config(filepath, title, desc="补档", tid=21):
    config = {
        "line": "bda2",
        "limit": 3,
        "streamers": {
            filepath: {
                "copyright": 2,
                "source": f"https://space.bilibili.com/{UID}/video",
                "tid": tid,
                "cover": "",
                "title": title,
                "desc_format_id": 0,
                "desc": desc,
                "dynamic": "",
                "tag": "补档",
                "dtime": None,
                "open_subtitle": False
            }
        }
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)

def upload_deleted_videos():
    conn = init_db()
    cur = conn.cursor()
    cur.execute("select id, title, downloaded_at from videos where status='deleted'")
    rows = cur.fetchall()

    if not rows:
        print("😴 没有需要补档的视频")
        return

    for vid, title, _ in rows:
        filepath = None
        for ext in [".mp4", ".flv", ".mkv"]:
            candidate = DOWNLOAD_DIR + "/" + f"{title} [{vid}]{ext}"
            if os.path.exists(candidate):
                filepath = DOWNLOAD_DIR + "/*" + f"{vid}" + "*"
                break

        if not filepath:
            print(f"❌ 本地找不到文件，跳过: {title} ({vid})")
            continue

        # 构建配置
        build_config(filepath, title)

        cmd = ["biliup", "upload", "--config", CONFIG_PATH]
        print("🚀 上传命令:", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True)
            cur.execute("update videos set status='uploaded' where id=?", (vid,))
            conn.commit()
            print(f"✅ 上传成功并标记为 uploaded: {title} ({vid})")
            time.sleep(120)  # 避免触发风控
        except subprocess.CalledProcessError as e:
            print("⚠️ 上传失败:", e)
            break

if __name__ == "__main__":
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    print("==== 检查新视频并下载 ====")
    download_new_videos()
    print("==== 检查并补档 deleted 视频 ====")
    upload_deleted_videos()