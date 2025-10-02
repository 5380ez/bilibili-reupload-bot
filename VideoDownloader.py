import os
import sqlite3
import yt_dlp
import time
import subprocess
import yaml
from datetime import datetime

# 自定义参数
UID = 145709539  # up主uid
VIDEO_NUMBER = 3  # 批量下载视频数

UP_SPACE_URL = f"https://space.bilibili.com/{UID}/video"
DB_PATH = "mydb.db"
DOWNLOAD_DIR = f"./downloads/{UID}"
CONFIG_PATH = "config.yaml"
SLEEP_TIME = 60


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""create table if not exists videos
                    (
                        id            text primary key,
                        title         text,
                        downloaded_at integer,
                        status        text,
                        desc          text,
                        tags          text,
                        views         integer,
                        likes         integer,
                        comments      integer,
                        last_checked  integer
                    )""")
    conn.commit()
    return conn


def get_status_dict(conn):
    cur = conn.cursor()
    cur.execute("select id, status from videos")
    return {row[0]: row[1] for row in cur.fetchall()}


def save_video_record(conn, vid, title, status="online", desc="", tags="", views=0, likes=0, comments=0):
    now = int(time.time())
    cur = conn.cursor()
    cur.execute("""insert or replace into videos 
                   (id, title, downloaded_at, status, desc, tags, views, likes, comments, last_checked) 
                   values (?,?,?,?,?,?,?,?,?,?)""",
                (vid, title, now, status, desc, tags, views, likes, comments, now))
    conn.commit()


def download_new_videos():
    """检查并下载新视频，保存为 online"""
    conn = init_db()
    status_dict = get_status_dict(conn)  # 只用于 deleted 检测
    cur = conn.cursor()

    def hook(d):
        if d['status'] == 'finished':
            info = d['info_dict']
            vid = info.get('id')
            title = info.get('title')
            desc = info.get('description') or ""
            tags = ",".join(info.get('tags') or [])
            views = info.get('view_count') or 0
            likes = info.get('like_count') or 0
            comments = info.get('comment_count') or 0
            print(f"✅ 下载完成: {title} ({vid})")
            save_video_record(conn, vid, title, status="online",
                              desc=desc, tags=tags,
                              views=views, likes=likes, comments=comments)

    ydl_opts = {
        "outtmpl": f"{DOWNLOAD_DIR}/%(title)s [%(id)s].%(ext)s",
        "merge_output_format": "mp4",
        "playlistend": VIDEO_NUMBER,
        "progress_hooks": [hook],
        "cookiefile": "cookies.txt",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        playlist_dict = ydl.extract_info(UP_SPACE_URL, download=False)
        entries = playlist_dict.get("entries", []) or []
        online_ids = {e.get("id") for e in entries if e.get("id")}

        # 1) 检查数据库里原本 online 的视频是否下架
        for vid, status in status_dict.items():
            if status == "online" and vid not in online_ids:
                cur.execute("update videos set status='deleted' where id=?", (vid,))
                conn.commit()
                print(f"⚠️ 视频已下架，标记为 deleted: {vid}")
            elif status == "online":
                # 刷新还在线的视频的统计数据
                try:
                    with yt_dlp.YoutubeDL({"quiet": True, "cookiefile": "cookies.txt"}) as ydl2:
                        info = ydl2.extract_info(f"https://www.bilibili.com/video/{vid}", download=False)
                        views = info.get('view_count') or 0
                        likes = info.get('like_count') or 0
                        comments = info.get('comment_count') or 0
                        cur.execute("update videos set views=?, likes=?, comments=?, last_checked=? where id=?",
                                    (views, likes, comments, int(time.time()), vid))
                        conn.commit()
                        print(f"🔄 更新数据: {vid} 播放量:{views} 👍:{likes} 评论数:{comments}")
                except Exception as e:
                    print(f"⚠️ 无法刷新视频 {vid} 的信息: {e}")

        # 2) 下载数据库里没有的新视频
        to_download = []
        for e in entries:
            vid = e.get("id")
            if not vid:
                continue
            cur.execute("select 1 from videos where id=?", (vid,))
            exists = cur.fetchone()
            if not exists:  # 数据库完全没有 → 新视频
                to_download.append(f"https://www.bilibili.com/video/{vid}")

        if not to_download:
            print("😴 没有新视频。")
        else:
            print(f"🚀 准备下载 {len(to_download)} 个新视频...")
            ydl.download(to_download)

def build_config(filepath, title, desc="补档", tags="补档", tid=21):
    config = {
        "line": "bda2",
        "limit": 3,
        "streamers": {
            filepath: {
                "copyright": 2,
                "source": f"https://space.bilibili.com/{UID}",
                "tid": tid,
                "cover": "",
                "title": "[补档]" + title,
                "desc_format_id": 0,
                "desc": desc,
                "dynamic": "",
                "tag": "补档," + tags,
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
    cur.execute("select id, title, desc, tags, views, likes, comments, last_checked from videos where status='deleted'")
    rows = cur.fetchall()

    if not rows:
        print("😴 没有需要补档的视频")
        return

    for vid, title, desc, tags, views, likes, comments, last_checked in rows:
        filepath = None
        for ext in [".mp4", ".flv", ".mkv"]:
            candidate = DOWNLOAD_DIR + "/" + f"{title} [{vid}]{ext}"
            if os.path.exists(candidate):
                filepath = DOWNLOAD_DIR + "/*" + f"{vid}" + "*"
                break

        if not filepath:
            print(f"❌ 本地找不到文件，跳过: {title} ({vid})")
            continue
        last_checked_str = datetime.fromtimestamp(last_checked).strftime("%Y-%m-%d %H:%M:%S")
        final_desc = \
f"""原视频简介：{desc}
被下架前最后一次检测时间：{last_checked_str}
最后一次检测时播放量：{views}，点赞数：{likes}，评论数：{comments}
"""

        # 构建配置
        build_config(filepath, title, final_desc, tags)

        cmd = ["biliup", "upload", "--config", CONFIG_PATH]
        print("🚀 上传命令:", " ".join(cmd))
        try:
            subprocess.run(cmd, check=True)
            cur.execute("update videos set status='uploaded' where id=?", (vid,))
            conn.commit()
            print(f"✅ 上传成功并标记为 uploaded: {title} ({vid})")
            time.sleep(SLEEP_TIME)  # 避免触发风控
        except subprocess.CalledProcessError as e:
            print("⚠️ 上传失败:", e)
            break


if __name__ == "__main__":
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    print("==== 检查新视频并下载 ====")
    download_new_videos()
    print("==== 检查并补档 deleted 视频 ====")
    upload_deleted_videos()
