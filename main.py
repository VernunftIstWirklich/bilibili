# -*- coding: utf-8 -*-
"""
B站弹幕与评论情绪分析脚本（适用于 macOS + Microsoft Edge）
依赖库：selenium、requests、jieba、snownlp、matplotlib、wordcloud、Pillow
"""
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service
import requests, json, os, time, re
import jieba
from snownlp import SnowNLP
import matplotlib.pyplot as plt
from wordcloud import WordCloud
from matplotlib.font_manager import findfont, FontProperties

# 1. Edge WebDriver 路径检测（需事先安装 msedgedriver 并配置到 PATH&#8203;:contentReference[oaicite:6]{index=6}）
driver_path = None
try:
    import shutil
    driver_path = shutil.which("msedgedriver")
except:
    driver_path = None

if not driver_path:
    print("未找到 Edge WebDriver，请前往微软官网下载与当前 Edge 浏览器匹配的 msedgedriver，并将其可执行文件路径添加到系统PATH&#8203;:contentReference[oaicite:7]{index=7}。")
    exit(1)

# 2. 自动登录 B 站
cookies_file = 'cookies.json'
cookies = None
if os.path.exists(cookies_file):
    print("检测到已保存的Cookie，直接使用该Cookie登录。")
    with open(cookies_file, 'r') as f:
        cookies = json.load(f)
else:
    print("启动 Edge 浏览器进行登录...")
    edge_options = Options()
    edge_options.use_chromium = True
    service = Service(driver_path)
    driver = webdriver.Edge(service=service, options=edge_options)
    driver.get("https://passport.bilibili.com/login")
    print("请使用哔哩哔哩手机客户端扫描二维码登录...")
    # 等待用户扫码登录
    while True:
        all_cookies = driver.get_cookies()
        names = [c['name'] for c in all_cookies]
        if 'DedeUserID' in names:
            print("登录成功！")
            cookies = all_cookies
            # 保存 Cookie
            with open(cookies_file, 'w') as f:
                json.dump(cookies, f)
            print(f"已保存Cookie到 {cookies_file}")
            break
        time.sleep(1)
    driver.quit()

# 3. 使用 requests 会话模拟已登录状态
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36 Edg/114.0.1823.67"
})
if cookies:
    for c in cookies:
        session.cookies.set(c['name'], c['value'], domain=c.get('domain'), path=c.get('path'))

# 4. 获取视频信息（输入 BV 号）
bvid = input("请输入 B 站视频 BV 号（如 BV1xx411x7yZ）: ").strip()
api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
res = session.get(api_url)
data = res.json()
if data.get("code") != 0:
    print("未能获取视频信息，请检查 BV 号是否正确。")
    exit(1)
video_data = data['data']
title = video_data.get('title', '')
aid = video_data.get('aid', '')
pages = video_data.get('pages', [])
cids = [p.get('cid') for p in pages if 'cid' in p]
print(f"视频标题：{title}")
print(f"AV号（aid）：{aid}")
print(f"分P数量：{len(cids)}，CID 列表：{cids}")

# 5. 爬取弹幕数据
danmaku_texts = []
print("开始获取弹幕数据...")
for cid in cids:
    danmaku_url = f"https://comment.bilibili.com/{cid}.xml"
    try:
        d_resp = session.get(danmaku_url, timeout=10)
        d_resp.encoding = 'utf-8'
        xml_data = d_resp.text
        # 解析 XML，提取每条弹幕文本
        import xml.etree.ElementTree as ET
        xml_root = ET.fromstring(xml_data)
        for elem in xml_root.findall('d'):
            text = elem.text
            if text:
                danmaku_texts.append(text)
    except Exception as e:
        print(f"获取弹幕 (cid={cid}) 时出错：{e}")
print(f"共获取弹幕 {len(danmaku_texts)} 条")

# 6. 爬取评论数据（分页）
comment_texts = []
print("开始获取评论数据...")
page = 1
while True:
    comment_url = f"https://api.bilibili.com/x/v2/reply?type=1&oid={aid}&pn={page}&sort=2"
    res = session.get(comment_url)
    res_json = res.json()
    if res_json.get("code") != 0:
        print("评论接口返回错误或结束。")
        break
    replies = res_json.get('data', {}).get('replies')
    if not replies:
        break
    for reply in replies:
        msg = reply.get('content', {}).get('message', '')
        if msg:
            comment_texts.append(msg)
    print(f"获取评论第 {page} 页，共 {len(replies)} 条")
    page += 1
    time.sleep(0.5)
print(f"共获取评论 {len(comment_texts)} 条")

# 7. 文本合并与清洗（仅保留中文）
all_texts = danmaku_texts + comment_texts
pattern = re.compile(r'[^\u4e00-\u9fa5]')
clean_texts = []
for t in all_texts:
    zh = pattern.sub('', t)
    if zh:
        clean_texts.append(zh)
print(f"清洗后文本条数：{len(clean_texts)}")

# 8. 分词
print("开始进行中文分词...")
words = []
for text in clean_texts:
    tokens = jieba.lcut(text)
    for w in tokens:
        # 过滤单字符词（可选）
        if len(w) > 1:
            words.append(w)
word_string = " ".join(words)
print(f"分词完成，共获得词语 {len(words)} 个")

# 9. 情感分析（SnowNLP）
pos, neg, neu = 0, 0, 0
print("开始情感分析（SnowNLP）...")
for text in clean_texts:
    s = SnowNLP(text).sentiments  # 0 ~ 1 的情感概率值
    if s > 0.5:
        pos += 1
    elif s < 0.5:
        neg += 1
    else:
        neu += 1
total = pos + neg + neu
if total == 0:
    print("无文本用于情感分析。")
else:
    pos_pct = pos / total * 100
    neg_pct = neg / total * 100
    neu_pct = neu / total * 100
    print(f"正面评论：{pos} 条，占比 {pos_pct:.1f}%")
    print(f"中性评论：{neu} 条，占比 {neu_pct:.1f}%")
    print(f"负面评论：{neg} 条，占比 {neg_pct:.1f}%")

# 10. 绘制饼图
print("开始绘制情感比例饼图...")
# 设置中文字体（查找系统可用中文字体）
ch_font_path = None
for font_name in ["PingFang SC", "Songti SC", "STHeiti", "SimHei", "Microsoft YaHei", "Arial Unicode MS"]:
    try:
        fp = findfont(font_name, fallback_to_default=False)
        if os.path.exists(fp):
            ch_font_path = fp
            break
    except:
        continue
if ch_font_path:
    plt.rcParams['font.family'] = FontProperties(fname=ch_font_path).get_name()
else:
    print("未找到中文字体，图表可能出现中文乱码。")

plt.figure(figsize=(6,6))
sizes = [pos, neu, neg]
labels = [f"正面 {pos_pct:.1f}%", f"中性 {neu_pct:.1f}%", f"负面 {neg_pct:.1f}%"]
colors = ['#66b3ff', '#ffcc99', '#ff9999']
explode = (0.1, 0, 0)  # 突出显示第一项（正面）
plt.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', explode=explode, startangle=140)
plt.axis('equal')
plt.title(f"【{title}】弹幕+评论情感分布")
pie_filename = f"{title}_情感比例饼图.png"
plt.savefig(pie_filename)
plt.close()
print(f"情感比例饼图已保存为：{pie_filename}")

# 11. 绘制词云
print("开始绘制词云...")
if not ch_font_path:
    print("未找到中文字体，词云可能无法正确显示中文。")
wc = WordCloud(font_path=ch_font_path or None, width=800, height=600, background_color='white')
wc.generate(word_string)
plt.figure(figsize=(8,6))
plt.imshow(wc, interpolation='bilinear')
plt.axis("off")
plt.title(f"【{title}】关键词词云")
wc_filename = f"{title}_词云.png"
plt.savefig(wc_filename)
plt.close()
print(f"关键词词云已保存为：{wc_filename}")

print("脚本执行完成。")
