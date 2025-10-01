import os
import sqlite3
import yt_dlp
import time

UP_SPACE_URL = "https://space.bilibili.com/316568752/video"  # 换成你要的UP主空间
DB_PATH = "mydb.db"
DOWNLOAD_DIR = "./downloads"
VIDEO_NUMBER = 3  #检测最新视频数
def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""create table if not exists videos (
                        id text primary key,
                        title text,
                        downloaded_at integer
                    )""")
    conn.commit()
    return conn

def get_downloaded_ids(conn):
    """获取已下载过的视频ID集合"""
    cur = conn.cursor()
    cur.execute("select id from videos")
    return {row[0] for row in cur.fetchall()}

def save_video_record(conn, vid, title):
    """保存新下载视频记录"""
    cur = conn.cursor()
    cur.execute("insert or ignore into videos (id, title, downloaded_at) values (?,?,?)",
                (vid, title, int(time.time())))
    conn.commit()

def download_new_videos():
    conn = init_db()
    downloaded_ids = get_downloaded_ids(conn)

    def hook(d):
        """下载完成时的回调"""
        if d['status'] == 'finished':
            info = d['info_dict']
            vid = info.get('id')
            title = info.get('title')
            print(f"✅ 下载完成: {title} ({vid})")
            save_video_record(conn, vid, title)

    ydl_opts = {
        "outtmpl": f"{DOWNLOAD_DIR}/%(title)s [%(id)s].%(ext)s",
        "merge_output_format": "mp4",
        "playlistend": VIDEO_NUMBER,
        "progress_hooks": [hook],
        # 注意：yt-dlp 会自己跳过已存在文件，这里我们额外用数据库做二次判断
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        # --flat-playlist 可以先只获取视频列表，不下载
        playlist_dict = ydl.extract_info(UP_SPACE_URL, download=False)
        entries = playlist_dict.get("entries", [])

        to_download = []
        for e in entries:
            vid = e.get("id")
            if vid not in downloaded_ids:
                to_download.append(f"https://www.bilibili.com/video/{vid}")

        if not to_download:
            print("😴 没有新视频，无需下载。")
        else:
            print(f"🚀 准备下载 {len(to_download)} 个新视频...")
            ydl.download(to_download)

if __name__ == "__main__":
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    download_new_videos()
