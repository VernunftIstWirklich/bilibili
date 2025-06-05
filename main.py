# main.py - 用于分析B站视频弹幕和评论的脚本 (集成Selenium登录和情感词频提取)

import asyncio
import os
import re
import sys # 确保导入sys模块
import json # 用于读写cookies
import time # 用于等待登录
import random # 用于生成随机字符串
import string # 用于生成随机字符串
from collections import Counter
import pandas as pd # 用于读取CSV文件和输出Excel, 确保已安装: pip install pandas openpyxl

# Selenium 相关导入
from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.common.exceptions import TimeoutException, WebDriverException

# 其他分析库
import jieba # 确保已安装: pip install jieba
import matplotlib.pyplot as plt # 确保已安装: pip install matplotlib
from matplotlib.font_manager import FontProperties # 用于设置中文字体
# 核心的 bilibili_api 导入
from bilibili_api import Credential, Danmaku, comment # 从顶层导入其他组件
from bilibili_api.video import Video # 尝试从 bilibili_api.video 子模块导入 Video 类
from bilibili_api.comment import CommentResourceType # 尝试从 bilibili_api.comment 子模块导入 CommentResourceType

from wordcloud import WordCloud # 确保已安装: pip install wordcloud
from snownlp import SnowNLP # 确保已安装: pip install snownlp

# Fuzzy matching library (optional)
try:
    from thefuzz import fuzz
    THEFUZZ_AVAILABLE = True
except ImportError:
    THEFUZZ_AVAILABLE = False
    print("警告: `thefuzz` 库未找到。将无法使用模糊匹配功能进行节目名称筛选。")
    print("      若需此功能, 请安装: pip install thefuzz python-Levenshtein")


# --- 配置区域 ---
OUTPUT_DIR = "analysis_results"
DANMAKU_TXT_FILE = os.path.join(OUTPUT_DIR, "danmaku_combined.txt") # 所有片段合并后的弹幕
OVERALL_WORDCLOUD_IMAGE_FILE = os.path.join(OUTPUT_DIR, "wordcloud_overall_from_txt.png") # 基于TXT的总词云图
SEGMENTED_FREQUENCY_REPORT_CSV = os.path.join(OUTPUT_DIR, "segmented_danmaku_frequency_report.csv") # 分段词频报告
OVERALL_SENTIMENT_PIE_CHART_FILE = os.path.join(OUTPUT_DIR, "comment_sentiment_pie_overall.png") # 总体评论情感饼图

# --- 新增配置 (常规情感分析) ---
SENTIMENT_WORDS_EXCEL_FILE = os.path.join(OUTPUT_DIR, "sentiment_specific_word_frequencies.xlsx") # 情感高频词输出文件
TOP_N_SENTIMENT_WORDS = 30 # 每个情感类别提取的最高频词数量 (用于Excel输出)

# --- 新增配置 (传统文化节目专项分析) ---
TRADITIONAL_CULTURE_PROGRAM_NAMES_OR_KEYWORDS = [
    "典籍里的中国", "国家宝藏", "中国诗词大会", "上新了·故宫", "如果国宝会说话", 
    "经典咏流传", "舞千年", "中国节日系列", "古韵新声", "国家人文历史"
    # 用户可以修改或扩展这个列表，用于识别CSV中的传统文化节目
    # 可以是节目名称的完整匹配，或者是能唯一识别节目的关键词
    # 示例：如果CSV中有 "典籍里的中国S2E01"，关键词 "典籍里的中国" 就能匹配
]
EXCLUDE_WORDS_FROM_FREQUENCY_ANALYSIS = ["贺电", "发来贺电"] # 传统文化节目词频分析时排除的词或短语中的关键词(分词后的单个词)
TOP_N_TRADITIONAL_FREQ_WORDS = 10 # 传统文化弹幕词频分析的Top N
TOP_N_TRADITIONAL_SENTIMENT_WORDS = 10 # 传统文化弹幕典型情感词的Top N

# --- AI/Fuzzy Matching Configuration ---
USE_FUZZY_MATCHING_FOR_PROGRAM_FILTER = True  # True: 尝试模糊匹配节目名; False: 使用精确子字符串匹配
FUZZY_MATCH_THRESHOLD = 80  # 0-100, 模糊匹配的相似度阈值 (建议 75-90)


EDGE_DRIVER_PATH = None # 例如 "C:/path/to/your/msedgedriver.exe" 或 "/usr/local/bin/msedgedriver"
COOKIES_FILE = "bilibili_cookies.json"
CSV_FILE_PATH = "2025年大学生网络春晚文本分析_数据表_2025年大学生春晚节目切片.csv" 
# 请确保CSV文件与脚本在同一目录，或提供完整路径

# --- 字体路径自动检测与配置 ---
def get_font_path_for_os():
    """
    自动检测操作系统并返回一个可用的中文字体路径。
    如果未找到，则返回 None，并打印警告。
    """
    font_path = None
    os_platform = sys.platform
    # print(f"当前操作系统平台: {os_platform}")

    if os_platform == "darwin":  # macOS
        macos_fonts = [
            "/System/Library/Fonts/PingFang.ttc", "/Library/Fonts/Songti.ttc",
            "/System/Library/Fonts/STHeitiLight.ttc", "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/Arial Unicode.ttf"
        ]
        font_search_list = macos_fonts
        os_name = "macOS"
    elif os_platform == "win32":  # Windows
        windows_fonts = [
            "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simsun.ttc",
            "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/kaiu.ttf",
        ]
        font_search_list = windows_fonts
        os_name = "Windows"
    elif os_platform.startswith("linux"): # Linux
        linux_fonts = [
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-SC-Regular.otf",
            "/usr/share/fonts/opentype/noto/NotoSerifCJK-SC-Regular.otf",
        ]
        font_search_list = linux_fonts
        os_name = "Linux"
    else:
        print(f"未知的操作系统平台: {os_platform}。将无法自动选择中文字体。")
        return None

    # print(f"正在为 {os_name} 尝试查找中文字体...")
    for font in font_search_list:
        if os.path.exists(font):
            font_path = font
            print(f"信息: 自动检测到并选用系统字体: {font_path}")
            break
    
    if not font_path:
        print(f"警告: 在 {os_name} 上未能从预设列表中自动检测到可用的中文字体。")
        print("图表和词云图中的中文可能无法正确显示。")
        print("您可以尝试在脚本顶部手动设置 FONT_PATH 为您系统中的有效中文字体路径。")
    return font_path

FONT_PATH = get_font_path_for_os() # 动态设置全局字体路径

# --- 情感标签映射 ---
sentiment_label_chinese_map = {
    'positive': '积极',
    'neutral': '中立',
    'negative': '消极'
}

# --- 辅助函数 ---
def time_to_seconds(time_str):
    """将 HH:MM:SS 或 MM:SS 格式的时间字符串转换为总秒数。"""
    if not isinstance(time_str, str):
        if isinstance(time_str, (int, float)):
             # print(f"警告: 时间值 '{time_str}' 是数字而非字符串，将尝试按秒处理，但这可能不是预期行为。请确保CSV中的时间格式为文本。")
             return int(time_str) 
        raise ValueError(f"时间必须是字符串格式, 收到: {time_str} (类型: {type(time_str)})")
    
    time_str = time_str.strip() 
    if time_str.endswith(".0"): 
        time_str = time_str[:-2]

    parts = list(map(int, time_str.split(':')))
    if len(parts) == 3: # HH:MM:SS
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    elif len(parts) == 2: # MM:SS
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
        
        segment_name_col = '节目名称' # Ensure this matches your CSV column name
        timeline_col = '时间轴' 
        page_num_col = 'P号' 

        required_cols = [segment_name_col, timeline_col]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            print(f"错误: CSV文件 '{csv_path}' 中缺少必需的列: {', '.join(missing_cols)}")
            print(f"CSV文件中的实际列名: {df.columns.tolist()}")
            return None

        print(f"成功读取CSV文件 '{csv_path}'。正在处理行...")
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
                        print(f"警告: 片段 '{segment_name}' のP号 '{row[page_num_col]}' 无效, 将使用默认P1 (page_index 0)。")
                except ValueError:
                    print(f"警告: 片段 '{segment_name}' のP号 '{row[page_num_col]}' 不是有效数字, 将使用默认P1 (page_index 0)。")
            
            match = time_pattern.search(timeline_str)
            if not match:
                print(f"警告: 片段 '{segment_name}' の '时间轴' ('{timeline_str}') 格式不符合预期 (例如 'HH:MM:SS-HH:MM:SS' 或 'MM:SS-MM:SS')。跳过此片段。")
                continue

            start_time_str = match.group(1)
            end_time_str = match.group(2)
            
            try:
                start_seconds = time_to_seconds(start_time_str)
                end_seconds = time_to_seconds(end_time_str)
            except ValueError as e:
                print(f"错误: 处理片段 '{segment_name}' の时间格式时出错 (从 '时间轴' 解析出: 开始='{start_time_str}', 结束='{end_time_str}'): {e}。跳过此片段。")
                continue
            
            if end_seconds <= start_seconds:
                print(f"警告: 片段 '{segment_name}' の结束时间 ({end_time_str}) 不大于开始时间 ({start_time_str})。跳过此片段。")
                continue

            from_seg = start_seconds // 360 # B站弹幕API按6分钟（360秒）分段
            to_seg = (end_seconds - 1) // 360 

            segments[segment_name] = {
                "page_index": page_index,
                "cid": None, # 将在获取视频信息后填充
                "from_seg": from_seg,
                "to_seg": to_seg
            }
            # print(f"  已加载片段: '{segment_name}', P索引: {page_index}, '时间轴': '{timeline_str}', 开始秒: {start_seconds}, 结束秒: {end_seconds}, from_seg: {from_seg}, to_seg: {to_seg}")

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

# --- Selenium 登录与 Cookie 管理 --- 
def get_bilibili_credential_via_selenium():
    """通过Selenium登录B站或加载已保存的Cookies来获取凭证。"""
    loaded_cookies = {}
    if os.path.exists(COOKIES_FILE):
        try:
            with open(COOKIES_FILE, 'r', encoding='utf-8') as f:
                loaded_cookies = json.load(f)
            # print(f"已从 {COOKIES_FILE} 加载Cookies。")
            if loaded_cookies.get("SESSDATA") and loaded_cookies.get("bili_jct"):
                 # print("检测到有效的SESSDATA和bili_jct，尝试使用已保存的Cookies。")
                 return Credential(
                    sessdata=loaded_cookies.get("SESSDATA"),
                    bili_jct=loaded_cookies.get("bili_jct"),
                    buvid3=loaded_cookies.get("buvid3"),
                    dedeuserid=loaded_cookies.get("DedeUserID") # DedeUserID 可能是大写或小写
                )
            else:
                print("加载的Cookies无效或不完整，将尝试重新登录。")
        except Exception as e:
            print(f"加载Cookies文件 {COOKIES_FILE} 失败: {e}。将尝试重新登录。")

    print("\n重要提示: 在脚本尝试启动Edge进行登录前，请确保已关闭所有正在运行的Microsoft Edge浏览器窗口。")
    print("这有助于避免 'user data directory is already in use' 错误。")
    print("\n正在启动Edge浏览器以登录Bilibili...")
    edge_options = EdgeOptions()
    edge_options.add_argument("--disable-gpu")
    edge_options.add_argument("--no-sandbox")
    edge_options.add_argument("--disable-dev-shm-usage")
    edge_options.add_experimental_option('excludeSwitches', ['enable-logging']) # 减少控制台日志
    edge_options.add_argument("--disable-extensions") # 禁用扩展
    edge_options.add_argument("--no-first-run") # 跳过首次运行向导
    edge_options.add_argument("--disable-background-networking") # 禁用后台网络活动
    edge_options.add_argument("--disable-sync") # 禁用同步

    # 创建唯一的user-data-dir以避免冲突
    timestamp = str(int(time.time()))
    random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    user_data_dir_base = "edge_user_data_profile_for_script"
    script_dir = os.path.dirname(os.path.abspath(__file__)) # 获取脚本所在目录
    user_data_dir = os.path.join(script_dir, "selenium_profiles", f"{user_data_dir_base}_{timestamp}_{random_suffix}")
    
    try:
        if not os.path.exists(os.path.dirname(user_data_dir)): # 确保 selenium_profiles 目录存在
            os.makedirs(os.path.dirname(user_data_dir))
    except Exception as e_mkdir:
        print(f"创建用户数据目录的父目录时出错: {e_mkdir}")
        # 即使创建失败，也尝试继续，WebDriver可能会自己处理

    edge_options.add_argument(f"--user-data-dir={user_data_dir}")
    # print(f"Edge WebDriver 将使用唯一的用户数据目录: {user_data_dir}")

    driver = None
    msedgedriver_path_in_system_for_error_msg = "未检测到或shutil不可用" # 用于错误消息
    try:
        msedgedriver_path_in_system = None
        try:
            import shutil
            msedgedriver_path_in_system = shutil.which("msedgedriver") or shutil.which("msedgedriver.exe")
            msedgedriver_path_in_system_for_error_msg = msedgedriver_path_in_system if msedgedriver_path_in_system else "未在PATH中找到"
        except ImportError:
             print("警告: `shutil` 模块未找到，无法自动检查 `msedgedriver` 是否在 PATH 中。")
        except Exception as e_shutil:
             print(f"检查 msedgedriver 路径时发生错误: {e_shutil}")

        if EDGE_DRIVER_PATH and os.path.exists(EDGE_DRIVER_PATH):
            # print(f"使用脚本中配置的 msedgedriver 路径: {EDGE_DRIVER_PATH}")
            service = EdgeService(executable_path=EDGE_DRIVER_PATH)
            driver = webdriver.Edge(service=service, options=edge_options)
        elif msedgedriver_path_in_system:
            # print(f"在系统PATH中找到 msedgedriver: {msedgedriver_path_in_system}")
            service = EdgeService(executable_path=msedgedriver_path_in_system) 
            driver = webdriver.Edge(service=service, options=edge_options)
        else:
            print("错误: 未在系统PATH或脚本中配置有效的 msedgedriver 路径。请检查配置。")
            print(f"  系统PATH中的msedgedriver检测结果: {msedgedriver_path_in_system_for_error_msg}")
            print(f"  脚本配置的msedgedriver路径 (EDGE_DRIVER_PATH): {EDGE_DRIVER_PATH if EDGE_DRIVER_PATH else '未配置'}")
            return None # 无法启动WebDriver

        print("Edge浏览器已启动。")
        driver.get("https://passport.bilibili.com/login")
        print("请在打开的浏览器窗口中手动登录Bilibili。脚本将等待60秒以便您完成登录。")
        time.sleep(60) # 增加等待时间以便用户登录
        print("尝试获取登录后的Cookies...")
        selenium_cookies = driver.get_cookies()

        if not selenium_cookies:
            print("未能获取到任何Cookies。请确保您已成功登录。")
            if driver: driver.quit() # 确保浏览器关闭
            return None

        b_cookies = {}
        for cookie_item in selenium_cookies: # B站的cookie通常在 .bilibili.com 域名下
            if 'bilibili.com' in cookie_item.get('domain', ''):
                b_cookies[cookie_item['name']] = cookie_item['value']

        sessdata = b_cookies.get("SESSDATA")
        bili_jct = b_cookies.get("bili_jct")
        buvid3 = b_cookies.get("buvid3") # buvid3也可能有用
        dedeuserid = b_cookies.get("DedeUserID") or b_cookies.get("dedeuserid") # DedeUserID有时是小写

        if sessdata and bili_jct:
            print("成功获取到SESSDATA和bili_jct。")
            cookies_to_save = {"SESSDATA": sessdata, "bili_jct": bili_jct, "buvid3": buvid3, "DedeUserID": dedeuserid}
            try:
                with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
                    json.dump(cookies_to_save, f, ensure_ascii=False, indent=4)
                print(f"Cookies已保存到 {COOKIES_FILE}")
            except Exception as e:
                print(f"保存Cookies到 {COOKIES_FILE} 时出错: {e}")
            if driver: driver.quit() # 确保浏览器关闭
            return Credential(sessdata=sessdata, bili_jct=bili_jct, buvid3=buvid3, dedeuserid=dedeuserid)
        else:
            print("登录后未能从Cookies中提取到SESSDATA或bili_jct。请检查登录状态。")
            if driver: driver.quit() # 确保浏览器关闭
            return None
    except WebDriverException as e:
        print(f"启动或操作Edge WebDriver时发生严重错误: {e}")
        if "user data directory is already in use" in str(e):
            print("错误提示：请关闭所有正在运行的Edge浏览器实例，然后重试。")
        if driver: driver.quit()
        return None
    except Exception as e:
        print(f"获取Cookies过程中发生未知错误: {e}")
        if driver: driver.quit()
        return None
    finally:
        if driver:
            driver.quit()
        # 清理用户数据目录
        if os.path.exists(user_data_dir):
            try:
                import shutil # 确保shutil已导入
                shutil.rmtree(user_data_dir)
                # print(f"已清理临时的Edge用户数据目录: {user_data_dir}")
            except Exception as e_rm:
                print(f"清理用户数据目录 {user_data_dir} 时出错: {e_rm}")


# --- 辅助函数 (文本处理与停用词) ---
def ensure_dir(directory_path):
    if not os.path.exists(directory_path):
        os.makedirs(directory_path)
        print(f"已创建目录: {directory_path}")

def load_stopwords(filepath="stopwords.txt"):
    """加载停用词列表，如果文件不存在则使用默认列表。"""
    default_stopwords = {"的", "了", "是", "我", "你", "他", "她", "它", "们", "这", "那", "一个", "一些", "什么", "怎么", "这个", "那个", "啊", "吧", "吗", "呢", "哈", "哈哈", "哈哈哈", "哦", "嗯", "草", "一种", "一样", "这样", "那样", "我们", "你们", "他们", "因为", "所以", "而且", "但是", "然而", " ", "\n", "\t"}
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                custom_stopwords = {line.strip().lower() for line in f if line.strip()}
                # print(f"已从 {filepath} 加载 {len(custom_stopwords)} 个自定义停用词。")
                return default_stopwords.union(custom_stopwords)
        except Exception as e:
            print(f"读取停用词文件 {filepath} 时出错: {e}。将使用默认停用词。")
            return default_stopwords
    else:
        # print(f"停用词文件 {filepath} 未找到。将使用默认的基础停用词集合。")
        return default_stopwords

STOPWORDS = load_stopwords()

def preprocess_text(text, custom_filter_words=None):
    """预处理文本：移除URL、提及、表情，保留中英数空格，分词，去停用词和自定义过滤词。"""
    # 移除URL
    text = re.sub(r"http\S+", "", text)
    # 移除@用户
    text = re.sub(r"@\S+", "", text)
    # 移除B站表情等中括号内容
    text = re.sub(r"\[.*?\]", "", text)
    # 仅保留中文、英文、数字和空格，移除其他特殊符号
    text = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9\s]", "", text)
    text = text.strip()

    if not text:
        return []

    # 使用精确模式进行分词
    seg_list = jieba.lcut(text, cut_all=False)

    # 过滤停用词和单字（通常单个字意义不大，除非特定场景）
    words_after_stopwords = [
        word for word in seg_list
        if word.strip() and word.lower() not in STOPWORDS and len(word) > 1 
    ]

    # 过滤自定义词（通常用于词云图，避免某些词语过多出现）
    if custom_filter_words:
        custom_filter_lower = [cfw.lower() for cfw in custom_filter_words]
        final_filtered_words = [
            word for word in words_after_stopwords
            if not any(cfw_lower in word.lower() for cfw_lower in custom_filter_lower)
        ]
    else:
        final_filtered_words = words_after_stopwords

    return final_filtered_words

# --- 新增：情感分析与高频词提取辅助函数 ---
def classify_texts_by_sentiment(texts_list):
    """将文本列表按情感分类 (积极, 中立, 消极)"""
    categorized_texts = {'positive': [], 'neutral': [], 'negative': []}
    if not texts_list:
        return categorized_texts
        
    for text in texts_list:
        if not text or not text.strip():
            continue
        try:
            s = SnowNLP(text)
            score = s.sentiments
            if score > 0.65: # 阈值可调整
                categorized_texts['positive'].append(text)
            elif score < 0.35: # 阈值可调整
                categorized_texts['negative'].append(text)
            else:
                categorized_texts['neutral'].append(text)
        except Exception as e:
            # print(f"SnowNLP处理文本 '{text[:20]}...' 时出错: {e}，跳过此条。")
            categorized_texts['neutral'].append(text) # 出错时暂归为中性
    return categorized_texts

def get_top_n_words(texts_for_sentiment, top_n):
    """从给定情感类别的文本列表中提取高频词"""
    if not texts_for_sentiment:
        return []
    
    all_words = []
    for text in texts_for_sentiment:
        # 对于情感词频分析，通常不过滤如“贺电”这类词，除非有特殊需求
        # preprocess_text 的 custom_filter_words 参数在此处为 None
        all_words.extend(preprocess_text(text)) 
                                           
    if not all_words:
        return []
        
    word_counts = Counter(all_words)
    return word_counts.most_common(top_n)


# --- 弹幕处理 ---
async def fetch_and_save_danmaku(video_obj, segments_config, credential_obj):
    """获取并保存视频各片段的弹幕。"""
    segmented_danmaku_data = {} # 存储每个片段的弹幕文本列表
    all_danmaku_texts_combined = [] # 存储所有片段合并后的弹幕文本
    print("正在获取弹幕...")

    video_info_data = await video_obj.get_info() # 获取视频信息，包括各P的CID
    pages_info = video_info_data.get('pages', [])

    if not segments_config: # segments_config 来自CSV
        print("错误：视频片段定义 (segments_config) 为空。请检查CSV文件或其加载逻辑。")
        return {}

    for segment_name, config in segments_config.items():
        print(f"  正在处理片段: {segment_name}")
        page_index = config.get("page_index", 0) # CSV中定义的P号对应的索引 (P1 -> 0, P2 -> 1)
        cid = config.get("cid") # 初始为None，会尝试从pages_info填充

        # 如果CSV中没有指定CID，则从视频信息中获取
        if not cid: 
            if pages_info and page_index < len(pages_info):
                cid = pages_info[page_index]['cid']
                # print(f"    目标CID: {cid} (对应P{page_index + 1} '{pages_info[page_index]['part']}')")
            elif not pages_info and page_index == 0: # 单P视频
                cid = video_info_data.get('cid') # 直接从顶层获取CID
                if not cid:
                    print(f"    错误: 无法获取单P视频的CID。跳过片段 {segment_name}。")
                    continue
                # print(f"    目标CID: {cid} (单P视频)")
            else:
                print(f"    错误: 无法确定page_index {page_index}对应的CID (可能是P号超出范围)。跳过片段 {segment_name}。")
                continue
        
        from_seg_index = config.get("from_seg") # 弹幕开始的6分钟段索引
        to_seg_index = config.get("to_seg")     # 弹幕结束的6分钟段索引

        current_segment_danmakus_raw = [] # 存储原始Danmaku对象
        try:
            if from_seg_index is None or to_seg_index is None: # 如果CSV未指定时间范围，则获取该P全部分段
                # print(f"    警告: 片段 '{segment_name}' 的 from_seg 或 to_seg 未定义，尝试获取CID {cid} 的所有弹幕...")
                danmaku_view = await video_obj.get_danmaku_view(cid=cid)
                total_segments = danmaku_view.get("dm_seg", {}).get("total", 1) # 总共有多少个6分钟段
                # print(f"    CID {cid} 可用的总6分钟片段数: {total_segments}")
                if total_segments > 0:
                    current_segment_danmakus_raw = await video_obj.get_danmakus(cid=cid, from_seg=0, to_seg=max(0, total_segments - 1))
            else:
                # print(f"    正在获取CID {cid} 从6分钟片段 {from_seg_index} 到 {to_seg_index} 的弹幕")
                current_segment_danmakus_raw = await video_obj.get_danmakus(cid=cid, from_seg=from_seg_index, to_seg=to_seg_index)
            
        except Exception as e:
            print(f"    获取CID {cid} (片段 '{segment_name}') 的弹幕时出错: {e}")
            continue # 跳到下一个片段

        # 从Danmaku对象中提取文本
        segment_danmaku_texts = [d.text for d in current_segment_danmakus_raw if hasattr(d, 'text') and d.text and d.text.strip()]
        segmented_danmaku_data[segment_name] = segment_danmaku_texts
        all_danmaku_texts_combined.extend(segment_danmaku_texts)
        
        # print(f"    此片段获取到 {len(segment_danmaku_texts)} 条非空弹幕。")
        await asyncio.sleep(random.uniform(1.0, 2.5)) # 礼貌性延时，避免请求过于频繁

    if not all_danmaku_texts_combined:
        print("未获取到任何弹幕。跳过保存到TXT文件。")
        print("提示：请在B站视频页面上确认目标视频片段确实存在弹幕。")
        return {} # 返回空字典，以便后续判断

    # 保存所有合并的弹幕到TXT文件
    try:
        with open(DANMAKU_TXT_FILE, "w", encoding="utf-8") as f:
            for text in all_danmaku_texts_combined:
                f.write(text + "\n")
        print(f"所有片段的合并弹幕文本 ({len(all_danmaku_texts_combined)} 行) 已保存至 {DANMAKU_TXT_FILE}")
    except Exception as e:
        print(f"保存合并弹幕文件 {DANMAKU_TXT_FILE} 时出错: {e}")
    
    return segmented_danmaku_data # 返回包含各片段弹幕的字典

def analyze_danmaku_and_generate_wordclouds(segmented_danmaku_data, all_sentiment_word_data_for_excel):
    """
    对分段的弹幕数据进行词频分析、词云图生成，并提取情感高频词。
    (此函数主要用于生成各片段的词云图和Excel中的分段情感词)
    """
    if not segmented_danmaku_data:
        print("没有分段弹幕数据可供分析。")
        return

    custom_filter_for_wordcloud = ["贺电", "发来贺电", "恭喜"] # 词云图中希望过滤的词
    all_frequency_data_for_report = [] # 用于CSV报告

    print("\n--- 开始为每个片段生成词云图、词频统计和情感词频提取 (用于Excel) ---")
    for segment_name, danmaku_texts_for_segment in segmented_danmaku_data.items():
        # print(f"\n  正在分析片段: {segment_name}")
        if not danmaku_texts_for_segment:
            # print(f"    片段 '{segment_name}' 没有弹幕文本，跳过分析。")
            continue

        # 1. 常规词频与词云图 (与原逻辑类似)
        processed_words_segment_for_wc = []
        for text in danmaku_texts_for_segment:
            processed_words_segment_for_wc.extend(preprocess_text(text, custom_filter_words=custom_filter_for_wordcloud))
        
        if processed_words_segment_for_wc:
            word_counts_segment = Counter(processed_words_segment_for_wc)
            total_words_in_segment = sum(word_counts_segment.values())
            
            # print(f"    片段 '{segment_name}' (词云用) 词频最高的前20个词:")
            for rank, (word, count) in enumerate(word_counts_segment.most_common(20), 1):
                percentage = (count / total_words_in_segment) * 100 if total_words_in_segment > 0 else 0
                all_frequency_data_for_report.append({
                    "片段名称": segment_name, "排名": rank, "关键词": word,
                    "词频数量": count, "词频百分比(%)": f"{percentage:.2f}" 
                })

            font_prop_wc = FontProperties(fname=FONT_PATH) if FONT_PATH and os.path.exists(FONT_PATH) else None
            if font_prop_wc:
                safe_segment_name = re.sub(r'[\\/*?:"<>|]', "_", segment_name) # 文件名安全处理
                segment_wordcloud_filename = os.path.join(OUTPUT_DIR, f"wordcloud_segment_{safe_segment_name}.png")
                try:
                    wc_segment = WordCloud(
                        font_path=FONT_PATH, width=1000, height=700, background_color="white",
                        max_words=150, collocations=False # 避免词语组合
                    ).generate_from_frequencies(word_counts_segment)
                    plt.figure(figsize=(10, 7))
                    plt.imshow(wc_segment, interpolation="bilinear")
                    plt.axis("off")
                    plt.title(f"弹幕词云图 - 片段: {segment_name}", fontproperties=font_prop_wc, fontsize=14)
                    plt.savefig(segment_wordcloud_filename)
                    # print(f"    片段 '{segment_name}' 的词云图已保存至 {segment_wordcloud_filename}")
                    plt.close() 
                except Exception as e:
                    print(f"    为片段 '{segment_name}' 生成词云图时出错: {e}")
            # else:
                # print(f"    警告: 字体路径 '{FONT_PATH}' 未找到或无效。无法为片段 '{segment_name}' 生成词云图。")
        # else:
            # print(f"    片段 '{segment_name}' (词云用) 预处理后没有剩余词语。")

        # 2. 提取情感高频词 (用于Excel)
        # print(f"    正在为片段 '{segment_name}' 提取情感高频词 (Excel用)...")
        categorized_segment_danmaku = classify_texts_by_sentiment(danmaku_texts_for_segment)
        for sentiment_key, sentiment_texts in categorized_segment_danmaku.items():
            if sentiment_texts:
                top_words = get_top_n_words(sentiment_texts, TOP_N_SENTIMENT_WORDS) # 使用配置的TOP_N
                if top_words:
                    # print(f"      片段 '{segment_name}' - {sentiment_label_chinese_map[sentiment_key]} ({len(sentiment_texts)}条) 高频词 (Excel用):")
                    for word, freq in top_words:
                        # print(f"        {word}: {freq}") # 可选打印
                        all_sentiment_word_data_for_excel.append({
                            'Type': '弹幕', 'Scope': f'片段: {segment_name}',
                            'Sentiment': sentiment_label_chinese_map[sentiment_key],
                            'Word': word, 'Frequency': freq
                        })
    
    if all_frequency_data_for_report:
        try:
            freq_df = pd.DataFrame(all_frequency_data_for_report)
            freq_df.to_csv(SEGMENTED_FREQUENCY_REPORT_CSV, index=False, encoding='utf-8-sig')
            print(f"\n分段弹幕词频报告 (词云图用数据) 已保存至: {SEGMENTED_FREQUENCY_REPORT_CSV}")
        except Exception as e:
            print(f"保存分段词频报告时出错: {e}")


def analyze_overall_danmaku_from_txt(txt_filepath, wordcloud_filepath, all_sentiment_word_data_for_excel):
    """
    从合并的弹幕TXT文件进行总的词频分析、词云图生成，并提取情感高频词 (用于Excel)。
    """
    print(f"\n--- 开始基于 {txt_filepath} 的总弹幕分析 (词云图与Excel情感词) ---")
    if not os.path.exists(txt_filepath):
        print(f"错误: 合并弹幕文件 {txt_filepath} 未找到。跳过总弹幕分析。")
        return

    try:
        with open(txt_filepath, "r", encoding="utf-8") as f:
            all_danmaku_text_lines = [line.strip() for line in f.readlines() if line.strip()]
    except Exception as e:
        print(f"读取合并弹幕文件 {txt_filepath} 时出错: {e}")
        return
        
    if not all_danmaku_text_lines:
        print("合并弹幕文件为空，跳过总弹幕分析。")
        return

    # 1. 常规词频与词云图 (与原逻辑类似)
    filter_words_for_overall_wc = ["贺电", "发来贺电", "恭喜", "大学发来贺电", "学院发来贺电", "职业技术学院发来贺电", "科技大学发来贺电"]
    
    processed_words_for_cloud_display = []
    for text_line in all_danmaku_text_lines:
        processed_words_for_cloud_display.extend(preprocess_text(text_line, custom_filter_words=filter_words_for_overall_wc))
    
    if processed_words_for_cloud_display:
        word_counts_for_cloud_display = Counter(processed_words_for_cloud_display)
        # print("\n总弹幕 (词云用) 词频最高的30个词 (已过滤“贺电”类):")
        # for word, count in word_counts_for_cloud_display.most_common(30):
            # print(f"  {word}: {count}") # 可选打印

        font_prop_wc_overall = FontProperties(fname=FONT_PATH) if FONT_PATH and os.path.exists(FONT_PATH) else None
        if font_prop_wc_overall:
            try:
                wc_overall = WordCloud(
                    font_path=FONT_PATH, width=1200, height=800, background_color="white",
                    max_words=200, collocations=False 
                ).generate_from_frequencies(word_counts_for_cloud_display) 

                plt.figure(figsize=(12, 9))
                plt.imshow(wc_overall, interpolation="bilinear")
                plt.axis("off")
                plt.title("总弹幕词云图 (基于TXT, 已过滤)", fontproperties=font_prop_wc_overall, fontsize=16)
                plt.savefig(wordcloud_filepath) 
                print(f"总弹幕词云图已保存至 {wordcloud_filepath}")
                plt.close() 
            except Exception as e:
                print(f"生成总弹幕词云图时出错: {e}")
        # else:
            # print(f"错误: 字体路径 '{FONT_PATH}' 未找到或无效。无法生成总词云图。")
    # else:
        # print("过滤“贺电”类词语后，没有剩余词语可用于生成总词云图。")

    # 2. 提取情感高频词 (用于Excel)
    # print(f"\n  正在为总弹幕 (来自 {txt_filepath}) 提取情感高频词 (Excel用)...")
    categorized_overall_danmaku = classify_texts_by_sentiment(all_danmaku_text_lines)
    for sentiment_key, sentiment_texts in categorized_overall_danmaku.items():
        if sentiment_texts:
            top_words = get_top_n_words(sentiment_texts, TOP_N_SENTIMENT_WORDS) # 使用配置的TOP_N
            if top_words:
                # print(f"    总弹幕 - {sentiment_label_chinese_map[sentiment_key]} ({len(sentiment_texts)}条) 高频词 (Excel用):")
                for word, freq in top_words:
                    # print(f"      {word}: {freq}") # 可选打印
                    all_sentiment_word_data_for_excel.append({
                        'Type': '弹幕', 'Scope': '整体 (来自TXT)',
                        'Sentiment': sentiment_label_chinese_map[sentiment_key],
                        'Word': word, 'Frequency': freq
                    })


# --- 评论处理 ---
async def fetch_comments(video_obj, credential_obj):
    """获取视频的所有评论文本。"""
    print("\n正在获取评论...")
    all_comments_data = [] # 存储评论文本和ID，用于去重
    current_page_num = 1 
    fetched_comment_ids = set() # 用于跟踪已获取的评论ID，避免重复

    if not video_obj.aid: # 确保有AID才能获取评论
        print("错误: 视频对象缺少有效的AID (video_obj.aid)，无法获取评论。")
        return []

    while True:
        try:
            # print(f"  尝试获取评论第 {current_page_num} 页...") # 用于调试
            # 使用 bilibili_api 的 comment.get_comments 方法
            # 修正：直接使用 CommentResourceType.VIDEO (假设它本身是整数)
            comments_page = await comment.get_comments(
                video_obj.aid,                       # Positional OID
                CommentResourceType.VIDEO,           # Positional type (直接使用枚举成员)
                current_page_num,                    # Positional page number
                credential=credential_obj            # Keyword credential
            )
            
            if not comments_page or not comments_page.get('replies'):
                # print(f"  在第 {current_page_num} 页未找到更多评论，或已到达评论末尾。")
                break # 没有更多评论或API返回空
            
            current_page_replies = comments_page['replies']
            # print(f"  已获取第 {current_page_num} 页评论 (包含 {len(current_page_replies)} 条顶级回复)")

            new_comments_on_page = 0
            for reply in current_page_replies: # 遍历顶级评论
                if reply and reply.get('rpid') and reply['rpid'] not in fetched_comment_ids and \
                   reply.get('content') and reply['content'].get('message'):
                    all_comments_data.append({'text': reply['content']['message'], 'id': reply['rpid']})
                    fetched_comment_ids.add(reply['rpid'])
                    new_comments_on_page +=1
                
                # 检查并获取子评论 (通常只获取一级子评论)
                if reply and reply.get('replies'): # 'replies' 键下是子评论列表
                    for sub_reply in reply['replies']:
                        if sub_reply and sub_reply.get('rpid') and sub_reply['rpid'] not in fetched_comment_ids and \
                           sub_reply.get('content') and sub_reply['content'].get('message'):
                            all_comments_data.append({'text': sub_reply['content']['message'], 'id': sub_reply['rpid']})
                            fetched_comment_ids.add(sub_reply['rpid'])
                            new_comments_on_page += 1
            
            # 翻页逻辑
            current_page_num += 1 
            cursor_info = comments_page.get('cursor', {})
            if cursor_info.get('is_end', False): # API明确告知已到末尾
                 # print("  API返回已到达评论末尾 (is_end is True)。")
                 break
            if cursor_info.get('all_count', 0) > 0 and len(fetched_comment_ids) >= cursor_info.get('all_count', 0):
                 # print("  已获取评论数量达到API报告的总数。")
                 break
            if new_comments_on_page == 0 and current_page_num > 2: 
                # print(f"  在第 {current_page_num-1} 页未获取到新评论，可能已到末尾。")
                break


            await asyncio.sleep(random.uniform(1.5, 3.0)) # 礼貌性延时
        except TypeError as te: 
            print(f"  获取评论第 {current_page_num} 页时发生类型错误: {te}")
            print(f"  这可能是由于 bilibili_api 版本与预期参数不符。请检查API用法或库版本。")
            break 
        except Exception as e:
            print(f"  获取评论第 {current_page_num} 页时出错: {e}")
            break 

    print(f"总共获取到 {len(all_comments_data)} 条不重复的评论文本。")
    return [item['text'] for item in all_comments_data] 

def analyze_comment_sentiment(comment_texts, sentiment_categories_keywords, all_sentiment_word_data_for_excel):
    """
    分析评论情感，为总体及定义的各个类别生成饼图，并提取总体评论的情感高频词 (用于Excel)。
    """
    if not comment_texts:
        print("没有评论文本可供情感分析。")
        return

    # --- 辅助函数：绘制饼图 (确保中文显示) ---
    def plot_pie_chart(data_dict, chart_title, filename):
        sentiment_labels_cn_map = {
            'positive': '正面', 'neutral': '中性', 'negative': '负面'
        }
        active_labels = []
        active_sizes = []
        for sentiment_en, count in data_dict.items():
            if count > 0: # 只显示有数据的部分
                active_labels.append(f"{sentiment_labels_cn_map.get(sentiment_en, sentiment_en)} ({count}条)")
                active_sizes.append(count)
        
        if not active_sizes: # 如果没有数据，则不绘制
            # print(f"没有数据可用于绘制 '{chart_title}'。跳过图表生成 {filename}。")
            return
            
        colors = ['#66b3ff','#99ff99', '#ffcc99', '#ff9999', '#c2c2f0','#ffb3e6'] 
        
        plt.figure(figsize=(10, 8))
        
        font_prop = None
        if FONT_PATH and os.path.exists(FONT_PATH):
            try:
                font_prop = FontProperties(fname=FONT_PATH)
                if font_prop.get_name() not in plt.rcParams['font.sans-serif']:
                    plt.rcParams['font.sans-serif'].insert(0, font_prop.get_name())
            except Exception as e_font_load:
                # print(f"警告: 加载 FONT_PATH ('{FONT_PATH}') 失败: {e_font_load}。尝试备选字体。")
                font_prop = None

        if not font_prop: # 如果指定字体加载失败，尝试系统默认中文字体
            default_chinese_fonts = ['PingFang SC','Songti SC','STHeiti','SimHei', 'Microsoft YaHei', 'WenQuanYi Micro Hei', 'Noto Sans CJK SC']
            for font_name_try in default_chinese_fonts:
                try:
                    test_prop = FontProperties(family=font_name_try) # 尝试使用字体名
                    plt.rcParams['font.sans-serif'].insert(0, test_prop.get_name())
                    font_prop = test_prop 
                    # print(f"信息: 饼图使用备选系统字体: {test_prop.get_name()}")
                    break 
                except Exception: # 如果字体名无效或不存在，会出错
                    # Attempt to remove if added, to prevent issues with invalid font names in rcParams
                    try:
                        if test_prop.get_name() in plt.rcParams['font.sans-serif']: 
                            plt.rcParams['font.sans-serif'].remove(test_prop.get_name())
                    except Exception:
                        pass # Ignore if removal fails or test_prop name is problematic
                    continue
            # if not font_prop:
                 # print(f"警告：未能自动找到可用的中文字体。饼图中的中文可能无法正确显示。")

        plt.rcParams['axes.unicode_minus'] = False # 正确显示负号

        wedges, texts, autotexts = plt.pie(active_sizes, labels=active_labels, autopct='%1.1f%%', 
                                           startangle=140, colors=colors[:len(active_sizes)], 
                                           pctdistance=0.85) # 百分比显示在饼图内部
        if font_prop: # 如果成功获取字体属性，应用到文本上
            for text_obj in texts + autotexts:
                text_obj.set_fontproperties(font_prop)
        
        plt.title(chart_title, fontproperties=font_prop, fontsize=16) 
        plt.axis('equal') # 保证饼图是圆形
        plt.tight_layout() # 调整布局以防止标签重叠
        try:
            plt.savefig(filename)
            print(f"饼图已保存至 {filename}")
        except Exception as e:
            print(f"保存饼图 {filename} 时出错: {e}")
        plt.close() # 关闭图像，释放资源

    # 1. 总体情感分析 (饼图用) 和 总体情感高频词提取 (Excel用)
    print("\n--- 开始总体评论情感分析与高频词提取 (饼图与Excel) ---")
    sentiments_overall_counts = {'positive': 0, 'neutral': 0, 'negative': 0}
    
    categorized_all_comments = classify_texts_by_sentiment(comment_texts)

    for sentiment_key, texts in categorized_all_comments.items():
        sentiments_overall_counts[sentiment_key] = len(texts)
    
    # print(f"总体评论情感分布: 正面={sentiments_overall_counts['positive']}, 中性={sentiments_overall_counts['neutral']}, 负面={sentiments_overall_counts['negative']}")
    if sum(sentiments_overall_counts.values()) > 0:
        plot_pie_chart(sentiments_overall_counts, "评论区总体情感分布", OVERALL_SENTIMENT_PIE_CHART_FILE)
    # else:
        # print("没有总体评论情感数据可供绘制饼图。")

    # print("  正在为总体评论提取情感高频词 (Excel用)...")
    for sentiment_key, texts_in_category in categorized_all_comments.items():
        if texts_in_category:
            top_words = get_top_n_words(texts_in_category, TOP_N_SENTIMENT_WORDS) # 使用配置的TOP_N
            if top_words:
                # print(f"    总体评论 - {sentiment_label_chinese_map[sentiment_key]} ({len(texts_in_category)}条) 高频词 (Excel用):")
                for word, freq in top_words:
                    # print(f"      {word}: {freq}") # 可选打印
                    all_sentiment_word_data_for_excel.append({
                        'Type': '评论', 'Scope': '整体',
                        'Sentiment': sentiment_label_chinese_map[sentiment_key],
                        'Word': word, 'Frequency': freq
                    })

    # 2. 分类别情感分析 (仅饼图用, 不提取此类别的特定高频词到Excel，除非需求变更)
    if sentiment_categories_keywords:
        print("\n--- 开始分类别评论情感分析 (仅饼图) ---")
        for category_name, keywords in sentiment_categories_keywords.items():
            # print(f"\n  正在分析类别: {category_name}")
            category_specific_texts = []
            keywords_lower = [k.lower() for k in keywords] # 转换为小写以进行不区分大小写的匹配
            
            for text in comment_texts: 
                if not text or not text.strip():
                    continue
                text_lower = text.lower()
                if any(keyword in text_lower for keyword in keywords_lower): # 如果评论包含任一关键词
                    category_specific_texts.append(text)
            
            if category_specific_texts:
                # print(f"    找到 {len(category_specific_texts)} 条与 '{category_name}' 相关的评论。")
                categorized_topic_comments = classify_texts_by_sentiment(category_specific_texts)
                topic_sentiment_counts = {k: len(v) for k, v in categorized_topic_comments.items()}

                # print(f"    '{category_name}' 相关评论情感: 正面={topic_sentiment_counts['positive']}, 中性={topic_sentiment_counts['neutral']}, 负面={topic_sentiment_counts['negative']}")
                safe_category_name = re.sub(r'[\\/*?:"<>|]', "_", category_name) # 文件名安全
                category_pie_chart_filename = os.path.join(OUTPUT_DIR, f"comment_sentiment_pie_{safe_category_name}.png")
                plot_pie_chart(topic_sentiment_counts, f"与'{category_name}'相关评论的情感分布", category_pie_chart_filename)
            # else:
                # print(f"    未找到与 '{category_name}' 相关的评论，不生成饼图。")
    # else:
        # print("\n未提供分类别情感分析的关键词，跳过此部分。")

# --- 新增：传统文化节目弹幕专项分析函数 ---
def get_danmaku_for_specific_programs(all_segmented_danmaku, program_identifiers, use_fuzzy=False, fuzzy_threshold=80):
    """
    从所有分段弹幕中筛选出特定节目的弹幕。
    program_identifiers 可以是节目全名或关键词列表。
    use_fuzzy: 是否启用模糊匹配。
    fuzzy_threshold: 模糊匹配的相似度阈值。
    """
    combined_danmaku = []
    if not all_segmented_danmaku:
        print("警告 (get_danmaku_for_specific_programs): 传入的弹幕数据为空，无法筛选特定节目弹幕。")
        return combined_danmaku
    if not program_identifiers:
        print("警告 (get_danmaku_for_specific_programs): 未指定特定节目的名称或关键词 (TRADITIONAL_CULTURE_PROGRAM_NAMES_OR_KEYWORDS)，无法筛选。")
        return combined_danmaku

    print(f"\n--- 正在筛选传统文化节目的弹幕 ---")
    if use_fuzzy and THEFUZZ_AVAILABLE:
        print(f"筛选模式: 模糊匹配 (阈值: {fuzzy_threshold})")
    else:
        if use_fuzzy and not THEFUZZ_AVAILABLE:
            print("筛选模式: 精确子字符串匹配 (模糊匹配库 'thefuzz' 不可用)")
        else:
            print("筛选模式: 精确子字符串匹配")
    print(f"筛选依据 (节目名称或关键词): {program_identifiers}")

    found_programs_count = 0
    matched_segment_names = set()

    for segment_name_csv, danmaku_texts in all_segmented_danmaku.items():
        matched_by_identifier = None
        is_match = False
        segment_name_csv_lower = segment_name_csv.lower()

        for identifier in program_identifiers:
            identifier_lower = identifier.lower()
            if use_fuzzy and THEFUZZ_AVAILABLE:
                # Using partial_ratio which is good for finding if a shorter string (identifier) is part of a longer one (segment_name_csv)
                similarity_score = fuzz.partial_ratio(identifier_lower, segment_name_csv_lower)
                if similarity_score >= fuzzy_threshold:
                    is_match = True
                    matched_by_identifier = identifier
                    # print(f"  [模糊匹配成功] 片段: '{segment_name_csv}' (与关键词 '{identifier}' 相似度: {similarity_score}%)")
                    break 
            else:
                if identifier_lower in segment_name_csv_lower:
                    is_match = True
                    matched_by_identifier = identifier
                    # print(f"  [精确匹配成功] 片段: '{segment_name_csv}' (包含关键词 '{identifier}')")
                    break
        
        if is_match:
            if segment_name_csv not in matched_segment_names: # Count unique matched segments
                found_programs_count +=1
                matched_segment_names.add(segment_name_csv)
                print(f"  匹配到节目片段: '{segment_name_csv}' (通过关键词: '{matched_by_identifier}'). 添加 {len(danmaku_texts)} 条弹幕。")
            else: # Already added danmaku from this segment if identifiers overlap for the same segment
                print(f"  片段 '{segment_name_csv}' 已通过其他关键词匹配过，追加弹幕 (当前关键词: '{matched_by_identifier}')")
            combined_danmaku.extend(danmaku_texts)
        # else:
            # print(f"  [未匹配] 片段: '{segment_name_csv}'")


    if found_programs_count == 0:
        print(f"警告: 未能从已加载的片段中匹配到任何指定的传统文化节目。")
        print(f"  请检查 `TRADITIONAL_CULTURE_PROGRAM_NAMES_OR_KEYWORDS` 配置和CSV文件中的 '节目名称' 是否对应。")
        print(f"  当前CSV加载的片段名有: {list(all_segmented_danmaku.keys())[:10]} (最多显示前10个)")
    else:
        print(f"已汇总来自 {found_programs_count} 个独立匹配节目片段的总共 {len(combined_danmaku)} 条弹幕用于专项分析。")
    return combined_danmaku


def analyze_traditional_danmaku_word_frequency(danmaku_texts, top_n=10, exclude_exact_words=None):
    """
    1. 对传统文化节目的所有弹幕进行词频分析。
    结果展示为出现频次最高的关键词TopN表格（含占比，排除指定关键词）。
    """
    if not danmaku_texts:
        print("没有传统文化节目弹幕文本可供词频分析。")
        return []

    print(f"\n--- 传统文化节目弹幕 词频分析 (Top {top_n}) ---")
    
    exclude_set_lower = set()
    if exclude_exact_words:
        exclude_set_lower = {ex_k.lower() for ex_k in exclude_exact_words}
        print(f"将从词频统计中排除以下精确匹配的词语 (不区分大小写): {exclude_exact_words}")

    all_words_for_freq = []
    for text in danmaku_texts:
        # preprocess_text 进行分词、去停用词、去单字等
        processed_tokens = preprocess_text(text) # custom_filter_words=None 默认不过滤特定模式
        
        # 进一步排除 EXCLUDE_WORDS_FROM_FREQUENCY_ANALYSIS 中指定的精确词汇
        if exclude_set_lower:
            tokens_after_specific_exclusion = [
                token for token in processed_tokens if token.lower() not in exclude_set_lower
            ]
            all_words_for_freq.extend(tokens_after_specific_exclusion)
        else:
            all_words_for_freq.extend(processed_tokens)
            
    if not all_words_for_freq:
        print("预处理和指定词排除后，没有剩余词语可供分析。")
        return []

    word_counts = Counter(all_words_for_freq)
    total_valid_words = sum(word_counts.values())
    
    if total_valid_words == 0:
        print("词频统计结果为空 (所有词都被过滤或排除)。")
        return []

    top_words_data = []
    print("\n关键词 Top 10 (含占比):")
    print("------------------------------------------------------")
    print(f"| {'排名':<4} | {'关键词':<25} | {'频次':<8} | {'占比 (%)':<10} |")
    print("------------------------------------------------------")
    for i, (word, count) in enumerate(word_counts.most_common(top_n), 1):
        percentage = (count / total_valid_words) * 100 if total_valid_words > 0 else 0
        print(f"| {i:<4} | {word:<25} | {count:<8} | {percentage:>9.2f}% |") # 调整关键词宽度
        top_words_data.append({"rank": i, "word": word, "count": count, "percentage": percentage})
    print("------------------------------------------------------")
    
    return top_words_data

def analyze_traditional_danmaku_sentiment_distribution(danmaku_texts):
    """
    2. 对传统文化节目的所有弹幕进行情感分析，结果为积极，消极，中立三个种类，并给出三个种类分别占比。
    """
    if not danmaku_texts:
        print("没有传统文化节目弹幕文本可供情感分布分析。")
        return None

    print("\n--- 传统文化节目弹幕 情感分布分析 ---")
    
    # 使用已有的 classify_texts_by_sentiment 函数
    categorized_texts = classify_texts_by_sentiment(danmaku_texts) 

    positive_count = len(categorized_texts['positive'])
    negative_count = len(categorized_texts['negative'])
    neutral_count = len(categorized_texts['neutral'])
    total_analyzed = positive_count + negative_count + neutral_count

    if total_analyzed == 0:
        print("未能分析任何传统文化节目弹幕的情感。")
        return {'positive_percent': 0, 'negative_percent': 0, 'neutral_percent': 0,
                'counts': {'positive': 0, 'negative': 0, 'neutral': 0}, 'total': 0}

    positive_percent = (positive_count / total_analyzed) * 100
    negative_percent = (negative_count / total_analyzed) * 100
    neutral_percent = (neutral_count / total_analyzed) * 100

    print("\n情感分布结果:")
    print(f"  {sentiment_label_chinese_map['positive']}弹幕: {positive_count}条 ({positive_percent:.2f}%)")
    print(f"  {sentiment_label_chinese_map['negative']}弹幕: {negative_count}条 ({negative_percent:.2f}%)")
    print(f"  {sentiment_label_chinese_map['neutral']}弹幕: {neutral_count}条 ({neutral_percent:.2f}%)")
    print(f"  总计分析弹幕数: {total_analyzed}条")
    
    return {
        'positive_percent': positive_percent,
        'negative_percent': negative_percent,
        'neutral_percent': neutral_percent,
        'counts': {
            'positive': positive_count,
            'negative': negative_count,
            'neutral': neutral_count
        },
        'total': total_analyzed
    }

def extract_traditional_danmaku_typical_sentiment_words(danmaku_texts, top_n_per_sentiment=10):
    """
    3. 根据第二条分析的结果，将提取出的词整理，给出三类情感典型词清单（三种感情分开给）。
    """
    if not danmaku_texts:
        print("没有传统文化节目弹幕文本可供提取典型情感词。")
        return None
    
    print(f"\n--- 传统文化节目弹幕 典型情感词提取 (每类 Top {top_n_per_sentiment}) ---")

    # 复用情感分类结果，或重新分类
    categorized_texts = classify_texts_by_sentiment(danmaku_texts)

    typical_words_output = {'positive': [], 'negative': [], 'neutral': []}

    for sentiment_key, texts_in_category in categorized_texts.items():
        sentiment_label_cn = sentiment_label_chinese_map.get(sentiment_key, sentiment_key)
        print(f"\n  {sentiment_label_cn}情感典型词 (基于 {len(texts_in_category)} 条此类弹幕):")
        
        if texts_in_category:
            # 使用已有的 get_top_n_words 函数，它内部调用 preprocess_text
            # preprocess_text 默认不过滤特定模式的词，只用通用停用词和长度过滤
            # 这对于提取典型情感词是合适的，因为我们不想在这里过度过滤
            top_words_list = get_top_n_words(texts_in_category, top_n_per_sentiment)
            
            if top_words_list:
                for word, freq in top_words_list:
                    print(f"    - {word} (频次: {freq})")
                    typical_words_output[sentiment_key].append({"word": word, "frequency": freq})
            else:
                print(f"    未能提取到典型词汇。")
        else:
            print(f"    无此类弹幕。")
            
    return typical_words_output


# --- 主执行逻辑 ---
async def main():
    global FONT_PATH 
    # 确保全局配置可访问，或者通过参数传递给需要它们的函数
    global TRADITIONAL_CULTURE_PROGRAM_NAMES_OR_KEYWORDS
    global EXCLUDE_WORDS_FROM_FREQUENCY_ANALYSIS
    global TOP_N_TRADITIONAL_FREQ_WORDS
    global TOP_N_TRADITIONAL_SENTIMENT_WORDS
    global USE_FUZZY_MATCHING_FOR_PROGRAM_FILTER # Make fuzzy config global or pass as param
    global FUZZY_MATCH_THRESHOLD
    
    if not (FONT_PATH and os.path.exists(FONT_PATH)): # 再次检查字体
        detected_font = get_font_path_for_os()
        if detected_font:
            FONT_PATH = detected_font
        # else: FONT_PATH remains as is, subsequent checks will handle it

    # 用于存储所有情感高频词数据以便最后写入Excel (此列表用于原有的Excel输出逻辑)
    all_sentiment_word_data_for_excel = []

    video_segments_to_analyze = load_segments_from_csv(CSV_FILE_PATH)
    if video_segments_to_analyze is None:
        print(f"错误：未能从CSV文件 '{CSV_FILE_PATH}' 加载视频片段定义。脚本将退出。")
        return
    if not video_segments_to_analyze: 
        print(f"警告：从CSV文件 '{CSV_FILE_PATH}' 加载到的视频片段定义为空。可能无法处理任何弹幕片段。")
        
    while True:
        video_input_raw = input("请输入目标视频的BV号 (例如 BV1aBfZYuEe7) 或 AID (纯数字): ").strip() 
        if video_input_raw:
            if (video_input_raw.upper().startswith("BV") and len(video_input_raw) == 12 and video_input_raw[2:].isalnum()) or \
               (video_input_raw.isdigit()):
                break
            else:
                print("输入格式不正确。BV号应为 'BV' 开头加10位字母数字，AID应为纯数字。请重新输入。")
        else:
            print("输入不能为空，请重新输入。")
    
    video_input = video_input_raw 

    ensure_dir(OUTPUT_DIR)
    # print("Jieba已初始化。") # jieba在首次使用时会自动初始化
    if not (FONT_PATH and os.path.exists(FONT_PATH)):
        print(f"最终警告: 未能确定有效的中文字体路径 (当前 FONT_PATH: '{FONT_PATH}')。图表和词云图中文显示可能不正确。")

    print("\n--- 开始获取B站登录凭证 ---")
    credential = get_bilibili_credential_via_selenium()

    if not credential:
        print("未能获取B站登录凭证。脚本无法继续执行需要登录的操作。")
        return
    print("成功获取或加载B站登录凭证。")

    video = None 
    try:
        if video_input.upper().startswith("BV") : 
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
            video.aid = retrieved_aid # 确保video对象有aid属性，用于评论获取
            # print(f"视频 AID 已成功设置为: {video.aid}")
        elif not (hasattr(video, 'aid') and video.aid): # 如果get_info没返回aid且对象本身也没有
            print(f"错误: 从视频信息中未能获取有效的 AID。视频数据详情: {video_info_data}")
            return # 评论获取将失败
    except AttributeError as e_attr: # 例如 video 对象没有 get_info
        print(f"错误: 处理视频信息时发生属性错误。错误详情: {e_attr}")
        return 
    except Exception as e: 
        print(f"错误: 获取或处理视频 '{video_input}' 的信息时发生错误。请检查ID和网络连接。错误详情: {e}")
        return 

    print("\n--- 开始处理弹幕 (常规流程) ---")
    segmented_danmaku_result = {} # 初始化
    if video and video_segments_to_analyze: 
        segmented_danmaku_result = await fetch_and_save_danmaku(video, video_segments_to_analyze, credential)
        
        if segmented_danmaku_result: 
            # 常规分析：每个片段的词云图，总弹幕TXT的词云图，以及这些的情感词提取到Excel
            analyze_danmaku_and_generate_wordclouds(segmented_danmaku_result, all_sentiment_word_data_for_excel)
            if os.path.exists(DANMAKU_TXT_FILE):
                 analyze_overall_danmaku_from_txt(DANMAKU_TXT_FILE, OVERALL_WORDCLOUD_IMAGE_FILE, all_sentiment_word_data_for_excel)
            # else:
                # print(f"提示: 合并弹幕文件 {DANMAKU_TXT_FILE} 未生成，无法进行基于TXT的总弹幕情感词分析。")
            
            # --- 新增：针对传统文化节目的弹幕专项分析 ---
            if TRADITIONAL_CULTURE_PROGRAM_NAMES_OR_KEYWORDS:
                # 1. 筛选出传统文化节目的弹幕
                traditional_danmaku_texts = get_danmaku_for_specific_programs(
                    segmented_danmaku_result, 
                    TRADITIONAL_CULTURE_PROGRAM_NAMES_OR_KEYWORDS,
                    use_fuzzy=USE_FUZZY_MATCHING_FOR_PROGRAM_FILTER, # Pass fuzzy config
                    fuzzy_threshold=FUZZY_MATCH_THRESHOLD
                )

                if traditional_danmaku_texts:
                    # 1a. 词频分析 (Top N, 排除指定词)
                    analyze_traditional_danmaku_word_frequency(
                        traditional_danmaku_texts, 
                        top_n=TOP_N_TRADITIONAL_FREQ_WORDS, 
                        exclude_exact_words=EXCLUDE_WORDS_FROM_FREQUENCY_ANALYSIS
                    )

                    # 1b. 情感分布分析
                    analyze_traditional_danmaku_sentiment_distribution(
                        traditional_danmaku_texts
                    )
                    
                    # 1c. 典型情感词提取
                    extract_traditional_danmaku_typical_sentiment_words(
                        traditional_danmaku_texts, 
                        top_n_per_sentiment=TOP_N_TRADITIONAL_SENTIMENT_WORDS
                    )
                else:
                    print("\n未能收集到传统文化节目的弹幕，跳过其特定分析。")
            else:
                print("\n未配置传统文化节目关键词 (TRADITIONAL_CULTURE_PROGRAM_NAMES_OR_KEYWORDS)，跳过其特定分析。")
            # --- 传统文化节目专项分析结束 ---

        else:
            print("由于未获取到弹幕，跳过所有弹幕分析。")
    elif not video_segments_to_analyze:
        print("错误：视频片段定义为空，跳过弹幕处理。")
    # else: (video object not initialized, already handled)
    #     print("错误：Video对象未成功初始化，跳过弹幕处理。")


    if hasattr(video, 'aid') and video.aid:
        print("\n--- 开始处理评论 (常规流程) ---")
        comment_texts = await fetch_comments(video, credential)
        if comment_texts:
            # 定义评论区情感分析的分类关键词 (仅用于生成分类饼图，不影响Excel输出)
            comment_sentiment_categories_for_pie = { 
                "传统文化相关": ["传统文化", "文化自信", "中国文化", "古风", "历史", "传承", "非遗", "匠心", "诗词", "国粹", "民族的", "底蕴", "古代", "文物", "书画", "戏曲", "民乐"],
                "节目本身评价": ["节目", "主持人", "节奏", "制作", "内容", "形式", "舞台", "效果", "创意", "编排", "好看", "精彩", "无聊", "尬", "拉胯", "春晚", "大学生"] 
            }
            analyze_comment_sentiment(comment_texts, comment_sentiment_categories_for_pie, all_sentiment_word_data_for_excel)
        else:
            print("由于未获取到评论，跳过评论分析。")
    else:
        print("\n视频AID未知或无效，跳过评论处理。")

    # --- 保存情感高频词到Excel (此部分包含来自各片段弹幕、总弹幕TXT、总评论的情感词) ---
    if all_sentiment_word_data_for_excel:
        print(f"\n--- 正在保存常规分析提取的情感高频词到Excel文件: {SENTIMENT_WORDS_EXCEL_FILE} ---")
        try:
            df_sentiment_words = pd.DataFrame(all_sentiment_word_data_for_excel)
            df_sentiment_words.to_excel(SENTIMENT_WORDS_EXCEL_FILE, index=False, engine='openpyxl')
            print(f"情感高频词数据已成功保存至: {SENTIMENT_WORDS_EXCEL_FILE}")
        except Exception as e:
            print(f"保存情感高频词Excel文件时出错: {e}")
            print("请确保已安装 'openpyxl' 库: pip install openpyxl")
    # else:
        # print("\n未能提取任何用于Excel的情感高频词数据，不生成Excel文件。")

    print("\n处理完成。分析结果（如果生成）位于 'analysis_results' 目录中。")

if __name__ == "__main__":
    print("重要提示：开始运行脚本前，请确保已安装所需库：")
    print("  pip install bilibili-api-python selenium jieba snownlp matplotlib wordcloud pandas openpyxl httpx thefuzz python-Levenshtein") 
    print("并且已正确配置 msedgedriver (Edge WebDriver)。脚本会尝试自动检测中文字体。\n")

    if os.name == 'nt' and sys.version_info >= (3,8):
        # For Windows asyncio policy if needed (usually not required for this script type)
        # asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        pass

    asyncio.run(main())
