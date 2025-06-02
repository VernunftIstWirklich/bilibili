# main.py - 用于分析B站视频弹幕和评论的脚本 (集成Selenium登录)

import asyncio
import os
import re
import sys  # 确保导入sys模块
import json  # 用于读写cookies
import time  # 用于等待登录
import random  # 用于生成随机字符串
import string  # 用于生成随机字符串
from collections import Counter
import pandas as pd  # 用于读取CSV文件, 确保已安装: pip install pandas

# Selenium 相关导入
from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.common.exceptions import TimeoutException, WebDriverException

# 其他分析库
import jieba  # 确保已安装: pip install jieba
import matplotlib.pyplot as plt  # 确保已安装: pip install matplotlib
# 核心的 bilibili_api 导入
from bilibili_api import Credential, Danmaku, comment  # 从顶层导入其他组件
from bilibili_api.video import Video  # 尝试从 bilibili_api.video 子模块导入 Video 类
from bilibili_api.comment import CommentResourceType  # 尝试从 bilibili_api.comment 子模块导入 CommentResourceType

from wordcloud import WordCloud  # 确保已安装: pip install wordcloud
from snownlp import SnowNLP  # 确保已安装: pip install snownlp

# --- 配置区域 ---
# VIDEO_URL_OR_BV 此变量将在 main 函数中通过用户输入获取
OUTPUT_DIR = "analysis_results"
DANMAKU_TXT_FILE = os.path.join(OUTPUT_DIR, "danmaku_combined.txt")  # 所有片段合并后的弹幕
OVERALL_WORDCLOUD_IMAGE_FILE = os.path.join(OUTPUT_DIR, "wordcloud_overall.png")  # 总词云图
# 子词云图文件名将在函数内动态生成
OVERALL_SENTIMENT_PIE_CHART_FILE = os.path.join(OUTPUT_DIR, "comment_sentiment_pie_overall.png")  # 总体评论情感饼图
# 子类别情感饼图文件名将在函数内动态生成
FONT_PATH = "C:/Windows/Fonts/msyh.ttc"  # TODO: 重要 - 请务必正确设置此路径
EDGE_DRIVER_PATH = None
COOKIES_FILE = "bilibili_cookies.json"
# CSV文件路径，用于加载视频片段定义
CSV_FILE_PATH = "2025年大学生网络春晚文本分析_数据表_2025年大学生春晚节目切片.csv"  # 更新为用户提供的文件名


# --- 辅助函数 ---
def time_to_seconds(time_str):
    """将 HH:MM:SS 或 MM:SS 格式的时间字符串转换为总秒数。"""
    if not isinstance(time_str, str):
        if isinstance(time_str, (int, float)):
            print(
                f"警告: 时间值 '{time_str}' 是数字而非字符串，将尝试按秒处理，但这可能不是预期行为。请确保CSV中的时间格式为文本。")
            return int(time_str)
        raise ValueError(f"时间必须是字符串格式, 收到: {time_str} (类型: {type(time_str)})")

    time_str = time_str.strip()  # 去除可能的首尾空格
    if time_str.endswith(".0"):  # 处理 pandas 可能将数字转为 float 再转为 str 带来的 ".0"
        time_str = time_str[:-2]

    parts = list(map(int, time_str.split(':')))
    if len(parts) == 3:  # HH:MM:SS
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    elif len(parts) == 2:  # MM:SS
        return parts[0] * 60 + parts[1]
    else:
        raise ValueError(f"无效的时间格式: '{time_str}'. 请使用 HH:MM:SS 或 MM:SS。")


def load_segments_from_csv(csv_path):
    """从CSV文件加载视频片段定义，使用'时间轴'列解析时间。"""
    segments = {}
    try:
        try:
            df = pd.read_csv(csv_path, encoding='utf-8-sig')
        except UnicodeDecodeError:
            print(f"使用 utf-8-sig 读取CSV文件 '{csv_path}' 失败，尝试 gbk 编码...")
            df = pd.read_csv(csv_path, encoding='gbk')

        segment_name_col = '节目名称'
        timeline_col = '时间轴'  # 使用 '时间轴' 列
        page_num_col = 'P号'  # 1-indexed (可选)

        required_cols = [segment_name_col, timeline_col]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            print(f"错误: CSV文件 '{csv_path}' 中缺少必需的列: {', '.join(missing_cols)}")
            print(f"CSV文件中的实际列名: {df.columns.tolist()}")
            return None

        print(f"成功读取CSV文件 '{csv_path}'。正在处理行...")
        # 正则表达式匹配 "HH:MM:SS-HH:MM:SS" 或 "MM:SS-MM:SS" 格式，允许可选的章节标题
        # \d{1,2}:\d{2}(?::\d{2})? 匹配 H:MM:SS, HH:MM:SS, M:SS, MM:SS
        time_pattern = re.compile(r'(\d{1,2}:\d{2}(?::\d{2})?)\s*-\s*(\d{1,2}:\d{2}(?::\d{2})?)')

        for index, row in df.iterrows():
            segment_name = str(row[segment_name_col]).strip()
            timeline_str = str(row[timeline_col]).strip()

            page_index = 0
            if page_num_col in df.columns and pd.notna(row[page_num_col]):
                try:
                    page_number = int(float(str(row[page_num_col]).strip()))
                    if page_number >= 1:
                        page_index = page_number - 1
                    else:
                        print(
                            f"警告: 片段 '{segment_name}' 的P号 '{row[page_num_col]}' 无效, 将使用默认P1 (page_index 0)。")
                except ValueError:
                    print(
                        f"警告: 片段 '{segment_name}' 的P号 '{row[page_num_col]}' 不是有效数字, 将使用默认P1 (page_index 0)。")

            match = time_pattern.search(timeline_str)
            if not match:
                print(
                    f"警告: 片段 '{segment_name}' 的 '时间轴' ('{timeline_str}') 格式不符合预期 (例如 'HH:MM:SS-HH:MM:SS' 或 'MM:SS-MM:SS')。跳过此片段。")
                continue

            start_time_str = match.group(1)
            end_time_str = match.group(2)

            try:
                start_seconds = time_to_seconds(start_time_str)
                end_seconds = time_to_seconds(end_time_str)
            except ValueError as e:
                print(
                    f"错误: 处理片段 '{segment_name}' 的时间格式时出错 (从 '时间轴' 解析出: 开始='{start_time_str}', 结束='{end_time_str}'): {e}。跳过此片段。")
                continue

            if end_seconds <= start_seconds:
                print(
                    f"警告: 片段 '{segment_name}' 的结束时间 ({end_time_str}) 不大于开始时间 ({start_time_str})。跳过此片段。")
                continue

            from_seg = start_seconds // 360
            to_seg = (end_seconds - 1) // 360

            segments[segment_name] = {
                "page_index": page_index,
                "cid": None,
                "from_seg": from_seg,
                "to_seg": to_seg
            }
            print(
                f"  已加载片段: '{segment_name}', P索引: {page_index}, '时间轴': '{timeline_str}', 开始秒: {start_seconds}, 结束秒: {end_seconds}, from_seg: {from_seg}, to_seg: {to_seg}")

    except FileNotFoundError:
        print(f"错误: CSV文件未找到于路径: {csv_path}")
        return None
    except pd.errors.EmptyDataError:
        print(f"错误: CSV文件为空: {csv_path}")
        return None
    except Exception as e:
        print(f"读取或处理CSV文件 '{csv_path}' 时发生一般错误: {e}")
        return None

    if not segments:
        print(f"警告: 未能从CSV文件 '{csv_path}' 中加载任何有效的片段定义。")
    return segments


# --- Selenium 登录与 Cookie 管理 --- (与之前版本相同，此处省略以减少篇幅，实际脚本中保留)
def get_bilibili_credential_via_selenium():
    """
    通过Selenium Edge WebDriver获取Bilibili登录凭证 (SESSDATA, bili_jct等)。
    会尝试从本地文件加载cookies，如果失败则启动浏览器让用户手动登录。
    """
    loaded_cookies = {}
    if os.path.exists(COOKIES_FILE):
        try:
            with open(COOKIES_FILE, 'r', encoding='utf-8') as f:
                loaded_cookies = json.load(f)
            print(f"已从 {COOKIES_FILE} 加载Cookies。")
            if loaded_cookies.get("SESSDATA") and loaded_cookies.get("bili_jct"):
                print("检测到有效的SESSDATA和bili_jct，尝试使用已保存的Cookies。")
                return Credential(
                    sessdata=loaded_cookies.get("SESSDATA"),
                    bili_jct=loaded_cookies.get("bili_jct"),
                    buvid3=loaded_cookies.get("buvid3"),
                    dedeuserid=loaded_cookies.get("DedeUserID")
                )
            else:
                print("加载的Cookies无效或不完整，将尝试重新登录。")
                loaded_cookies = {}
        except Exception as e:
            print(f"加载Cookies文件 {COOKIES_FILE} 失败: {e}。将尝试重新登录。")
            loaded_cookies = {}

    print("\n重要提示: 在脚本尝试启动Edge进行登录前，请确保已关闭所有正在运行的Microsoft Edge浏览器窗口。")
    print("这有助于避免 'user data directory is already in use' 错误。")

    print("\n正在启动Edge浏览器以登录Bilibili...")
    edge_options = EdgeOptions()
    edge_options.add_argument("--disable-gpu")
    edge_options.add_argument("--no-sandbox")
    edge_options.add_argument("--disable-dev-shm-usage")
    edge_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    edge_options.add_argument("--disable-extensions")
    edge_options.add_argument("--no-first-run")
    edge_options.add_argument("--disable-background-networking")
    edge_options.add_argument("--disable-sync")

    timestamp = str(int(time.time()))
    random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    user_data_dir_base = "edge_user_data_profile_for_script"
    script_dir = os.path.dirname(os.path.abspath(__file__))
    user_data_dir = os.path.join(script_dir, "selenium_profiles", f"{user_data_dir_base}_{timestamp}_{random_suffix}")

    try:
        if not os.path.exists(os.path.dirname(user_data_dir)):
            os.makedirs(os.path.dirname(user_data_dir))
    except Exception as e_mkdir:
        print(f"创建用户数据目录的父目录时出错: {e_mkdir}")

    edge_options.add_argument(f"--user-data-dir={user_data_dir}")
    print(f"Edge WebDriver 将使用唯一的用户数据目录: {user_data_dir}")

    driver = None
    msedgedriver_path_in_system_for_error_msg = "未检测到或shutil不可用"
    try:
        msedgedriver_path_in_system = None
        try:
            import shutil
            msedgedriver_path_in_system = shutil.which("msedgedriver") or shutil.which("msedgedriver.exe")
            msedgedriver_path_in_system_for_error_msg = msedgedriver_path_in_system if msedgedriver_path_in_system else "未在PATH中找到"
            if not msedgedriver_path_in_system and not EDGE_DRIVER_PATH:
                print("错误: 未在系统PATH中找到 msedgedriver，并且脚本中的 EDGE_DRIVER_PATH 也未设置。")
                print("请将 msedgedriver.exe 添加到系统PATH环境变量，或者在脚本中明确指定 EDGE_DRIVER_PATH 的路径。")
        except ImportError:
            print("警告: `shutil` 模块未找到，无法自动检查 `msedgedriver` 是否在 PATH 中。")
        except Exception as e_shutil:
            print(f"检查 msedgedriver 路径时发生错误: {e_shutil}")

        if EDGE_DRIVER_PATH and os.path.exists(EDGE_DRIVER_PATH):
            print(f"使用脚本中指定的 EDGE_DRIVER_PATH: {EDGE_DRIVER_PATH}")
            service = EdgeService(executable_path=EDGE_DRIVER_PATH)
            driver = webdriver.Edge(service=service, options=edge_options)
        elif msedgedriver_path_in_system:
            print(f"在系统PATH中找到 msedgedriver: {msedgedriver_path_in_system}")
            service = EdgeService(executable_path=msedgedriver_path_in_system)
            driver = webdriver.Edge(service=service, options=edge_options)
        else:
            print("尝试让 Selenium 自动查找 msedgedriver (可能失败)...")
            driver = webdriver.Edge(options=edge_options)

        print("Edge浏览器已启动。")
        driver.get("https://passport.bilibili.com/login")
        print("请在打开的浏览器窗口中手动登录Bilibili。脚本将等待60秒以便您完成登录。")
        print("登录成功后，请确保页面已跳转到B站主页或您的个人空间。")
        time.sleep(60)

        print("尝试获取登录后的Cookies...")
        selenium_cookies = driver.get_cookies()

        if not selenium_cookies:
            print("未能获取到任何Cookies。请确保您已成功登录。")
            if driver: driver.quit()
            return None

        b_cookies = {}
        for cookie_item in selenium_cookies:
            if 'bilibili.com' in cookie_item.get('domain', ''):
                b_cookies[cookie_item['name']] = cookie_item['value']

        sessdata = b_cookies.get("SESSDATA")
        bili_jct = b_cookies.get("bili_jct")
        buvid3 = b_cookies.get("buvid3")
        dedeuserid = b_cookies.get("DedeUserID") or b_cookies.get("dedeuserid")

        if sessdata and bili_jct:
            print("成功获取到SESSDATA和bili_jct。")
            cookies_to_save = {
                "SESSDATA": sessdata,
                "bili_jct": bili_jct,
                "buvid3": buvid3,
                "DedeUserID": dedeuserid
            }
            try:
                with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
                    json.dump(cookies_to_save, f, ensure_ascii=False, indent=4)
                print(f"Cookies已保存到 {COOKIES_FILE}")
            except Exception as e:
                print(f"保存Cookies到 {COOKIES_FILE} 时出错: {e}")

            if driver: driver.quit()
            return Credential(
                sessdata=sessdata,
                bili_jct=bili_jct,
                buvid3=buvid3,
                dedeuserid=dedeuserid
            )
        else:
            print("登录后未能从Cookies中提取到SESSDATA或bili_jct。请检查登录状态。")
            if driver: driver.quit()
            return None

    except WebDriverException as e:
        print(f"启动或操作Edge WebDriver时发生严重错误: {e}")
        print("\n--- WebDriver 错误排查建议 ---")
        print("1. 确保 Microsoft Edge 浏览器已正确安装且为最新版本。")
        print(f"2. 确保 msedgedriver.exe 已下载，其版本与您的 Edge 浏览器版本严格匹配。")
        print(f"   当前脚本检测到系统PATH中的 msedgedriver 为: {msedgedriver_path_in_system_for_error_msg}")
        print(f"   脚本中配置的 EDGE_DRIVER_PATH 为: {EDGE_DRIVER_PATH if EDGE_DRIVER_PATH else '未设置'}")
        print("   请访问 https://developer.microsoft.com/en-us/microsoft-edge/tools/webdriver/ 下载。")
        print(
            "3. 确保 msedgedriver.exe 的路径已正确添加到系统PATH环境变量，或者在脚本中通过 EDGE_DRIVER_PATH 变量正确指定。")
        print("4. **关键操作：在运行此脚本前，请尝试手动关闭所有已打开的 Microsoft Edge 浏览器窗口和相关的后台进程。**")
        print("   您可以通过任务管理器 (Ctrl+Shift+Esc) 检查并结束名为 'msedge.exe' 和 'msedgedriver.exe' 的进程。")
        print("5. 错误信息中提及 'user data directory is already in use'：")
        user_data_dir_for_error_msg = user_data_dir if 'user_data_dir' in locals() else '未生成'
        print(f"   脚本已尝试使用一个唯一的用户数据目录: {user_data_dir_for_error_msg}")
        print("   如果此错误持续出现，表明即使使用了唯一目录，也可能存在更深层次的冲突或权限问题。")
        print(
            f"   尝试手动删除脚本目录下的 '{os.path.join(script_dir, 'selenium_profiles')}' 文件夹（如果存在），然后重试。")
        print("6. 检查是否有安全软件（如杀毒软件、防火墙）阻止了 msedgedriver 的正常运行。")
        print("7. 尝试以管理员权限运行您的PyCharm或命令行。")
        if "DevToolsActivePort file doesn't exist" in str(e):
            print("8. 错误信息包含 'DevToolsActivePort file doesn't exist'：这通常表示浏览器未能成功启动或过早崩溃。")
            print("   检查上述第1、2、4点。也可能是 msedgedriver 与浏览器版本不兼容的强烈信号。")
        if driver:
            try:
                driver.quit()
            except:
                pass
        return None
    except Exception as e:
        print(f"获取Cookies过程中发生未知错误: {e}")
        if driver:
            try:
                driver.quit()
            except:
                pass
        return None


# --- 辅助函数 (与之前脚本相同) ---
def ensure_dir(directory_path):
    if not os.path.exists(directory_path):
        os.makedirs(directory_path)
        print(f"已创建目录: {directory_path}")


def load_stopwords(filepath="stopwords.txt"):
    default_stopwords = {"的", "了", "是", "我", "你", "他", "她", "它", "们", "这", "那", "一个", "一些", "什么",
                         "怎么", "这个", "那个", "啊", "吧", "吗", "呢", "哈", "哈哈", "哈哈哈", "哦", "嗯", "草",
                         "一种", "一样", "这样", "那样", "我们", "你们", "他们", "因为", "所以", "而且", "但是", "然而",
                         " ", "\n", "\t"}
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                custom_stopwords = {line.strip().lower() for line in f if line.strip()}
                return default_stopwords.union(custom_stopwords)
        except Exception as e:
            print(f"读取停用词文件 {filepath} 时出错: {e}。将使用默认停用词。")
            return default_stopwords
    else:
        print(f"停用词文件 {filepath} 未找到。将使用默认的基础停用词集合。")
        return default_stopwords


STOPWORDS = load_stopwords()


def preprocess_text(text, custom_filter_words=None):
    text = re.sub(r"http\S+", "", text)
    text = re.sub(r"@\S+", "", text)
    text = re.sub(r"\[.*?\]", "", text)
    text = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9\s]", "", text)
    text = text.strip()

    if not text:
        return []

    seg_list = jieba.lcut(text, cut_all=False)

    words_after_stopwords = [
        word for word in seg_list
        if word.strip() and word.lower() not in STOPWORDS
    ]

    if custom_filter_words:
        custom_filter_lower = [cfw.lower() for cfw in custom_filter_words]
        final_filtered_words = [
            word for word in words_after_stopwords
            if not any(cfw_lower in word.lower() for cfw_lower in custom_filter_lower)
        ]
    else:
        final_filtered_words = words_after_stopwords

    return final_filtered_words


# VIDEO_SEGMENTS_TO_ANALYZE 将在 main 函数中通过 load_segments_from_csv 加载

# --- 弹幕处理 ---
async def fetch_and_save_danmaku(video_obj, segments_config, credential_obj):
    """
    获取指定片段的弹幕。
    返回一个字典，键是片段名，值是该片段的弹幕文本列表。
    同时，将所有弹幕合并保存到 DANMAKU_TXT_FILE。
    """
    segmented_danmaku_data = {}
    all_danmaku_texts_combined = []
    print("正在获取弹幕...")

    video_info_data = await video_obj.get_info()
    pages_info = video_info_data.get('pages', [])

    if not segments_config:
        print("错误：视频片段定义 (VIDEO_SEGMENTS_TO_ANALYZE) 为空。请检查CSV文件或其加载逻辑。")
        return {}

    for segment_name, config in segments_config.items():
        print(f"  正在处理片段: {segment_name}")
        page_index = config.get("page_index", 0)
        cid = config.get("cid")

        if not cid:
            if pages_info and page_index < len(pages_info):
                cid = pages_info[page_index]['cid']
                print(f"    目标CID: {cid} (对应P{page_index + 1} '{pages_info[page_index]['part']}')")
            elif not pages_info and page_index == 0:
                cid = video_info_data.get('cid')
                if not cid:
                    print(f"    错误: 无法获取单P视频的CID。跳过片段 {segment_name}。")
                    continue
                print(f"    目标CID: {cid} (单P视频)")
            else:
                print(f"    错误: 无法确定page_index {page_index}对应的CID。跳过片段 {segment_name}。")
                continue

        from_seg_index = config.get("from_seg")
        to_seg_index = config.get("to_seg")

        current_segment_danmakus_raw = []
        try:
            if from_seg_index is None or to_seg_index is None:
                print(f"    警告: 片段 '{segment_name}' 的 from_seg 或 to_seg 未定义，尝试获取所有弹幕...")
                danmaku_view = await video_obj.get_danmaku_view(cid=cid)
                print(f"    Danmaku view for CID {cid}: {danmaku_view}")
                total_segments = danmaku_view.get("dm_seg", {}).get("total", 1)
                print(f"    CID {cid} 可用的总6分钟片段数: {total_segments}")
                if total_segments > 0:
                    current_segment_danmakus_raw = await video_obj.get_danmakus(cid=cid, from_seg=0,
                                                                                to_seg=max(0, total_segments - 1))
            else:
                print(f"    正在获取CID {cid} 从6分钟片段 {from_seg_index} 到 {to_seg_index} 的弹幕")
                current_segment_danmakus_raw = await video_obj.get_danmakus(cid=cid, from_seg=from_seg_index,
                                                                            to_seg=to_seg_index)

            print(f"    Raw danmaku object list for this segment (first 5 if many): {current_segment_danmakus_raw[:5]}")
            if current_segment_danmakus_raw:
                print("    Inspecting attributes of fetched Danmaku objects:")
                for i, d_obj in enumerate(current_segment_danmakus_raw[:5]):
                    try:
                        text_content = getattr(d_obj, 'text', 'N/A')
                        dm_time_val = getattr(d_obj, 'dm_time', 'N/A')
                        mode_val = getattr(d_obj, 'mode', 'N/A')
                        id_str_val = getattr(d_obj, 'id_str', 'N/A')
                        print(
                            f"      Danmaku obj {i}: text='{text_content}', time='{dm_time_val}', mode='{mode_val}', id_str='{id_str_val}'")
                    except Exception as e_inspect:
                        print(f"      Error inspecting Danmaku obj {i}: {e_inspect}. Object: {d_obj}")
        except Exception as e:
            print(f"    获取CID {cid} (片段 '{segment_name}') 的弹幕时出错: {e}")
            continue

        segment_danmaku_texts = [d.text for d in current_segment_danmakus_raw if
                                 hasattr(d, 'text') and d.text and d.text.strip()]
        segmented_danmaku_data[segment_name] = segment_danmaku_texts
        all_danmaku_texts_combined.extend(segment_danmaku_texts)

        print(f"    此片段获取到 {len(segment_danmaku_texts)} 条非空弹幕。")
        await asyncio.sleep(1)

    if not all_danmaku_texts_combined:
        print("未获取到任何弹幕。跳过保存到TXT文件。")
        print("提示：请在B站视频页面上确认目标视频片段确实存在弹幕。")
        return {}

    try:
        with open(DANMAKU_TXT_FILE, "w", encoding="utf-8") as f:
            for text in all_danmaku_texts_combined:
                f.write(text + "\n")
        print(f"所有片段的合并弹幕文本 ({len(all_danmaku_texts_combined)} 行) 已保存至 {DANMAKU_TXT_FILE}")
    except Exception as e:
        print(f"保存合并弹幕文件 {DANMAKU_TXT_FILE} 时出错: {e}")

    return segmented_danmaku_data


def analyze_danmaku_and_generate_wordclouds(segmented_danmaku_data):
    """
    对分段的弹幕数据进行词频分析，并为每个片段及总体生成词云图。
    segmented_danmaku_data: 字典，键是片段名，值是该片段的弹幕文本列表。
    """
    if not segmented_danmaku_data:
        print("没有分段弹幕数据可供分析。")
        return

    custom_filter_for_wordcloud = ["贺电", "发来贺电", "恭喜"]
    all_danmaku_texts_combined_for_overall_wc = []

    print("\n--- 开始为每个片段生成词云图和词频统计 ---")
    for segment_name, danmaku_texts_for_segment in segmented_danmaku_data.items():
        print(f"\n  正在分析片段: {segment_name}")
        if not danmaku_texts_for_segment:
            print(f"    片段 '{segment_name}' 没有弹幕文本，跳过分析。")
            continue

        all_danmaku_texts_combined_for_overall_wc.extend(danmaku_texts_for_segment)

        processed_words_segment = []
        for text in danmaku_texts_for_segment:
            processed_words_segment.extend(preprocess_text(text, custom_filter_words=custom_filter_for_wordcloud))

        if not processed_words_segment:
            print(f"    片段 '{segment_name}' 预处理后没有剩余词语，跳过词频分析和词云图。")
            continue

        word_counts_segment = Counter(processed_words_segment)
        print(f"    片段 '{segment_name}' 词频最高的30个词:")
        for word, count in word_counts_segment.most_common(30):
            print(f"      {word}: {count}")

        if not FONT_PATH or not os.path.exists(FONT_PATH):
            print(f"    错误: 字体路径 '{FONT_PATH}' 未找到或未设置。无法为片段 '{segment_name}' 生成词云图。")
            continue

        safe_segment_name = re.sub(r'[\\/*?:"<>|]', "", segment_name)
        segment_wordcloud_filename = os.path.join(OUTPUT_DIR, f"wordcloud_segment_{safe_segment_name}.png")
        try:
            wc_segment = WordCloud(
                font_path=FONT_PATH,
                width=1000,
                height=700,
                background_color="white",
                max_words=150,
                collocations=False
            ).generate_from_frequencies(word_counts_segment)

            plt.figure(figsize=(10, 7))
            plt.imshow(wc_segment, interpolation="bilinear")
            plt.axis("off")
            title_font_props = None
            try:
                from matplotlib.font_manager import FontProperties
                title_font_props = FontProperties(fname=FONT_PATH)
            except Exception as e_font:
                print(f"    警告：为片段 '{segment_name}' 词云图标题加载字体属性失败 {FONT_PATH}。错误：{e_font}")
            plt.title(f"弹幕词云图 - 片段: {segment_name}", fontproperties=title_font_props, fontsize=14)
            plt.savefig(segment_wordcloud_filename)
            print(f"    片段 '{segment_name}' 的词云图已保存至 {segment_wordcloud_filename}")
            plt.close()
        except Exception as e:
            print(f"    为片段 '{segment_name}' 生成词云图时出错: {e}")

    print("\n--- 开始生成总词云图和词频统计 ---")
    if not all_danmaku_texts_combined_for_overall_wc:
        print("没有合并的弹幕文本可用于生成总词云图。")
        return

    processed_words_overall = []
    for text in all_danmaku_texts_combined_for_overall_wc:
        processed_words_overall.extend(preprocess_text(text, custom_filter_words=custom_filter_for_wordcloud))

    if not processed_words_overall:
        print("所有弹幕预处理后没有剩余词语，无法生成总词云图。")
        return

    word_counts_overall = Counter(processed_words_overall)
    print("总词频最高的30个词 (已过滤词云图干扰词):")
    for word, count in word_counts_overall.most_common(30):
        print(f"  {word}: {count}")

    if not FONT_PATH or not os.path.exists(FONT_PATH):
        print(f"错误: 字体路径 '{FONT_PATH}' 未找到或未设置。无法生成总词云图。")
        return

    try:
        wc_overall = WordCloud(
            font_path=FONT_PATH,
            width=1200,
            height=800,
            background_color="white",
            max_words=200,
            collocations=False
        ).generate_from_frequencies(word_counts_overall)

        plt.figure(figsize=(12, 9))
        plt.imshow(wc_overall, interpolation="bilinear")
        plt.axis("off")
        title_font_props_overall = None
        try:
            from matplotlib.font_manager import FontProperties
            title_font_props_overall = FontProperties(fname=FONT_PATH)
        except Exception as e_font_overall:
            print(f"警告：为总词云图标题加载字体属性失败 {FONT_PATH}。错误：{e_font_overall}")
        plt.title("总弹幕词云图 (Overall Danmaku Word Cloud)", fontproperties=title_font_props_overall, fontsize=16)
        plt.savefig(OVERALL_WORDCLOUD_IMAGE_FILE)
        print(f"总词云图已保存至 {OVERALL_WORDCLOUD_IMAGE_FILE}")
        plt.close()
    except Exception as e:
        print(f"生成总词云图时出错: {e}")


# --- 评论处理 ---
async def fetch_comments(video_obj, credential_obj):
    print("\n正在获取评论...")
    all_comments_data = []
    current_page_num = 1
    fetched_comment_ids = set()

    if not video_obj.aid:
        print("错误: 视频对象缺少有效的AID (video_obj.aid)，无法获取评论。")
        return []

    while True:
        try:
            comments_page = await comment.get_comments(
                video_obj.aid,
                CommentResourceType.VIDEO,
                current_page_num,
                credential=credential_obj
            )

            if not comments_page or not comments_page.get('replies'):
                print(f"  在第 {current_page_num} 页未找到更多评论，或已到达评论末尾。")
                break

            current_page_replies = comments_page['replies']
            print(f"  已获取第 {current_page_num} 页评论 (包含 {len(current_page_replies)} 条顶级回复)")

            for reply in current_page_replies:
                if reply and reply.get('rpid') and reply['rpid'] not in fetched_comment_ids and reply.get('content') and \
                        reply['content'].get('message'):
                    all_comments_data.append({'text': reply['content']['message'], 'id': reply['rpid']})
                    fetched_comment_ids.add(reply['rpid'])

                if reply and reply.get('replies'):
                    for sub_reply in reply['replies']:
                        if sub_reply and sub_reply.get('rpid') and sub_reply[
                            'rpid'] not in fetched_comment_ids and sub_reply.get('content') and sub_reply[
                            'content'].get('message'):
                            all_comments_data.append({'text': sub_reply['content']['message'], 'id': sub_reply['rpid']})
                            fetched_comment_ids.add(sub_reply['rpid'])

            current_page_num += 1
            cursor_info = comments_page.get('cursor', {})
            if cursor_info.get('is_end', False):
                print("  API返回已到达评论末尾 (is_end is True)。")
                break
            if cursor_info.get('all_count', 0) > 0 and len(fetched_comment_ids) >= cursor_info.get('all_count', 0):
                print("  已获取评论数量达到API报告的总数。")
                break
            if not current_page_replies and current_page_num > 1:
                print("  当前评论页为空，可能已到达末尾。")
                break

            await asyncio.sleep(1.5)
        except TypeError as te:
            print(f"  获取评论第 {current_page_num} 页时发生类型错误 (参数可能不匹配): {te}")
            print(f"  当前尝试的调用方式是 get_comments(oid, type, page_num (作为位置参数), credential=...)")
            print(f"  oid={video_obj.aid}, type_={CommentResourceType.VIDEO}, page_num={current_page_num}")
            print(f"  如果此错误持续，请检查 bilibili-api 库的 get_comments 函数签名。")
            break
        except Exception as e:
            print(f"  获取评论第 {current_page_num} 页时出错: {e}")
            break

    print(f"总共获取到 {len(all_comments_data)} 条不重复的评论文本。")
    return [item['text'] for item in all_comments_data]


def analyze_comment_sentiment(comment_texts, sentiment_categories_keywords=None):
    """
    分析评论情感，并为总体及定义的各个类别生成饼图。
    comment_texts: 所有评论文本的列表。
    sentiment_categories_keywords: 字典，键是类别名，值是该类别的关键词列表。
                                   例如: {"传统文化": ["古风", "历史"], "节目本身": ["主持人", "节奏"]}
    """
    if not comment_texts:
        print("没有评论文本可供情感分析。")
        return

    # --- 辅助函数：绘制饼图 ---
    def plot_pie_chart(data_dict, chart_title, filename):
        active_labels = [f"{k} ({v}条)" for k, v in data_dict.items() if v > 0]
        active_sizes = [v for v in data_dict.values() if v > 0]

        if not active_sizes:
            print(f"没有数据可用于绘制 '{chart_title}'。跳过图表生成 {filename}。")
            return

        colors = ['#66b3ff', '#99ff99', '#ffcc99']  # 积极、中性、消极

        plt.figure(figsize=(10, 8))
        plt.pie(active_sizes, labels=active_labels, autopct='%1.1f%%', startangle=140,
                colors=colors[:len(active_sizes)], pctdistance=0.85)

        title_font_props_pie = None
        if FONT_PATH and os.path.exists(FONT_PATH):
            try:
                from matplotlib.font_manager import FontProperties
                title_font_props_pie = FontProperties(fname=FONT_PATH)
            except Exception as e_font_pie:
                print(f"警告：为饼图 '{chart_title}' 标题加载字体属性失败 {FONT_PATH}。错误：{e_font_pie}")

        current_font_family = plt.rcParams.get('font.sans-serif', [])
        if title_font_props_pie:
            if title_font_props_pie.get_name() not in current_font_family:
                plt.rcParams['font.sans-serif'] = [title_font_props_pie.get_name()] + current_font_family
        elif not any(f_name in current_font_family for f_name in ['SimHei', 'Microsoft YaHei']):
            plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei'] + current_font_family

        plt.rcParams['axes.unicode_minus'] = False
        plt.title(chart_title, fontproperties=title_font_props_pie, fontsize=16)
        plt.axis('equal')
        plt.tight_layout()
        try:
            plt.savefig(filename)
            print(f"饼图已保存至 {filename}")
        except Exception as e:
            print(f"保存饼图 {filename} 时出错: {e}")
        plt.close()

    # 1. 总体情感分析
    print("\n--- 开始总体评论情感分析 ---")
    sentiments_overall = {'positive': 0, 'neutral': 0, 'negative': 0}
    processed_count_overall = 0
    for text in comment_texts:
        if not text or not text.strip():
            continue
        try:
            s = SnowNLP(text)
            score = s.sentiments
        except Exception as e:
            score = 0.5

        sentiment_category = ""
        if score > 0.65:
            sentiment_category = 'positive'
        elif score < 0.35:
            sentiment_category = 'negative'
        else:
            sentiment_category = 'neutral'
        sentiments_overall[sentiment_category] += 1
        processed_count_overall += 1
        if processed_count_overall % 200 == 0:
            print(f"  已处理 {processed_count_overall}/{len(comment_texts)} 条评论的总体情感分析...")

    print(
        f"总体情感分布: 正面={sentiments_overall['positive']}, 中性={sentiments_overall['neutral']}, 负面={sentiments_overall['negative']}")
    if sum(sentiments_overall.values()) > 0:
        plot_pie_chart(sentiments_overall, "评论区总体情感分布", OVERALL_SENTIMENT_PIE_CHART_FILE)
    else:
        print("没有总体评论情感数据可供绘制饼图。")

    # 2. 分类别情感分析
    if sentiment_categories_keywords:
        print("\n--- 开始分类别评论情感分析 ---")
        for category_name, keywords in sentiment_categories_keywords.items():
            print(f"\n  正在分析类别: {category_name}")
            sentiments_category = {'positive': 0, 'neutral': 0, 'negative': 0}
            category_comment_count = 0
            keywords_lower = [k.lower() for k in keywords]

            for text in comment_texts:
                if not text or not text.strip():
                    continue

                text_lower = text.lower()
                if any(keyword in text_lower for keyword in keywords_lower):
                    category_comment_count += 1
                    try:
                        s = SnowNLP(text)
                        score = s.sentiments
                    except Exception as e:
                        score = 0.5

                    sentiment_category_val = ""
                    if score > 0.65:
                        sentiment_category_val = 'positive'
                    elif score < 0.35:
                        sentiment_category_val = 'negative'
                    else:
                        sentiment_category_val = 'neutral'
                    sentiments_category[sentiment_category_val] += 1

            print(f"    找到 {category_comment_count} 条与 '{category_name}' 相关的评论。")
            if category_comment_count > 0:
                print(
                    f"    '{category_name}' 相关评论情感: 正面={sentiments_category['positive']}, 中性={sentiments_category['neutral']}, 负面={sentiments_category['negative']}")
                safe_category_name = re.sub(r'[\\/*?:"<>|]', "", category_name)
                category_pie_chart_filename = os.path.join(OUTPUT_DIR,
                                                           f"comment_sentiment_pie_{safe_category_name}.png")
                plot_pie_chart(sentiments_category, f"与'{category_name}'相关评论的情感分布",
                               category_pie_chart_filename)
            else:
                print(f"    未找到与 '{category_name}' 相关的评论，不生成饼图。")
    else:
        print("\n未提供分类别情感分析的关键词，跳过此部分。")


# --- 主执行逻辑 ---
async def main():
    video_segments_to_analyze = load_segments_from_csv(CSV_FILE_PATH)
    if video_segments_to_analyze is None:
        print(f"错误：未能从CSV文件 '{CSV_FILE_PATH}' 加载视频片段定义。脚本将退出。")
        print("请确保CSV文件存在，路径正确，且包含名为 '节目名称', '时间轴' (以及可选的 'P号') 的列。")
        return
    if not video_segments_to_analyze:
        print(f"警告：从CSV文件 '{CSV_FILE_PATH}' 加载到的视频片段定义为空。可能无法处理任何弹幕片段。")

    while True:
        video_input_raw = input("请输入目标视频的BV号 (例如 BV1aBfZYuEe7) 或 AID (纯数字): ").strip()
        if video_input_raw:
            if (video_input_raw.upper().startswith("BV") and len(video_input_raw) == 12 and video_input_raw[
                                                                                            2:].isalnum()) or \
                    (video_input_raw.isdigit()):
                break
            else:
                print("输入格式不正确。BV号应为 'BV' 开头加10位字母数字，AID应为纯数字。请重新输入。")
        else:
            print("输入不能为空，请重新输入。")

    video_input = video_input_raw

    ensure_dir(OUTPUT_DIR)

    print("Jieba已初始化。")
    if not os.path.exists(FONT_PATH) or FONT_PATH == "C:/Windows/Fonts/msyh.ttc":
        if FONT_PATH == "C:/Windows/Fonts/msyh.ttc" and not os.path.exists(FONT_PATH):
            print(
                f"提示: 默认字体路径 '{FONT_PATH}' (微软雅黑) 未找到。如果您使用的是非Windows系统，或未安装此字体，请务必修改 FONT_PATH。")
        elif FONT_PATH == "path/to/your/chinese_font.ttf":
            print(f"严重警告: 中文字体文件路径 FONT_PATH 仍为占位符 'path/to/your/chinese_font.ttf'。")
        elif not os.path.exists(FONT_PATH):
            print(f"严重警告: 中文字体文件未在 '{FONT_PATH}' 找到。")
        if not os.path.exists(FONT_PATH) or FONT_PATH == "path/to/your/chinese_font.ttf":
            print("词云图和带有中文标签的图表很可能无法生成或显示错误。请正确设置 FONT_PATH。")

    print("\n--- 开始获取B站登录凭证 ---")
    credential = get_bilibili_credential_via_selenium()

    if not credential:
        print("未能获取B站登录凭证。脚本无法继续执行需要登录的操作。")
        return
    print("成功获取或加载B站登录凭证。")

    video = None
    try:
        if video_input.upper().startswith("BV"):
            video = Video(bvid=video_input, credential=credential)
        elif video_input.isdigit():
            video = Video(aid=int(video_input), credential=credential)
        else:
            print(f"错误: 无法从 '{video_input}' 中识别视频ID。请输入有效的BV号或AID。")
            return
    except Exception as e:
        print(f"初始化Video对象时出错: {e}")
        return

    print(f"正在处理视频: {video_input}")
    try:
        video_info_data = await video.get_info()

        if not video_info_data or not video_info_data.get('title'):
            print(f"错误: 无法获取视频 '{video_input}' 的有效信息 (标题/数据缺失)。请检查ID和网络连接。")
            return
        print(f"已成功获取视频信息: {video_info_data.get('title', 'N/A')}")

        retrieved_aid = video_info_data.get('aid')
        if retrieved_aid:
            video.aid = retrieved_aid
            print(f"视频 AID 已成功设置为: {video.aid}")
        else:
            if hasattr(video, 'aid') and video.aid:
                print(f"从 get_info() 的返回字典中未直接找到 AID，但 video 对象已包含 AID: {video.aid}")
            else:
                print(f"错误: 从视频信息中未能获取有效的 AID。视频数据详情: {video_info_data}")
                print("由于无法确认视频 AID，评论获取等后续操作可能失败。")

    except AttributeError as e_attr:
        print(f"错误: 处理视频信息时发生属性错误。错误详情: {e_attr}")
        print("这可能与 bilibili_api 库的版本或视频对象的状态有关。")
        return
    except Exception as e:
        print(f"错误: 获取或处理视频 '{video_input}' 的信息时发生错误。请检查ID和网络连接。错误详情: {e}")
        return

    print("\n--- 开始处理弹幕 ---")
    if video and video_segments_to_analyze:
        segmented_danmaku_result = await fetch_and_save_danmaku(video, video_segments_to_analyze, credential)
        if segmented_danmaku_result:
            analyze_danmaku_and_generate_wordclouds(segmented_danmaku_result)
        else:
            print("由于未获取到弹幕，跳过弹幕分析。")
    elif not video_segments_to_analyze:
        print("错误：视频片段定义为空，跳过弹幕处理。")
    else:
        print("错误：Video对象未成功初始化，跳过弹幕处理。")

    if hasattr(video, 'aid') and video.aid:
        print("\n--- 开始处理评论 ---")
        comment_texts = await fetch_comments(video, credential)
        if comment_texts:
            comment_sentiment_categories = {
                "传统文化": ["传统文化", "文化自信", "中国文化", "古风", "历史", "传承", "非遗", "匠心", "诗词", "国粹",
                             "民族的", "底蕴", "古代", "文物", "书画", "戏曲", "民乐"],
                "节目本身": ["节目", "主持人", "节奏", "制作", "内容", "形式", "舞台", "效果", "创意", "编排", "好看",
                             "精彩", "无聊", "尬", "拉胯", "春晚", "大学生"]
            }
            analyze_comment_sentiment(comment_texts, sentiment_categories_keywords=comment_sentiment_categories)
        else:
            print("由于未获取到评论，跳过评论分析。")
    else:
        print("\n视频AID未知或无效，跳过评论处理。")

    print("\n处理完成。分析结果（如果生成）位于 'analysis_results' 目录中。")


if __name__ == "__main__":
    print("重要提示：开始运行脚本前，请确保已安装所需库：")
    print("  pip install bilibili-api-python selenium jieba snownlp matplotlib wordcloud httpx pandas")
    print("并且已正确配置 msedgedriver (Edge WebDriver) 和 FONT_PATH (中文字体路径)。")
    print("如果遇到 'ModuleNotFoundError', 请确认上述库已在您当前的Python环境中正确安装。\n")

    if os.name == 'nt' and sys.version_info >= (3, 8):
        pass

    asyncio.run(main())

