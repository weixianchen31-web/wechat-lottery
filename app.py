import os
import hashlib
import requests
import re
import time
from flask import Flask, request, make_response
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import pytz

app = Flask(__name__)

# ========== 配置 ==========
APPID       = os.environ.get("APPID",       "wxa45e4eecfad0521d")
APPSECRET   = os.environ.get("APPSECRET",   "f4bfd918f620924d96784a6f8c4e2d45")
TOKEN       = os.environ.get("TOKEN",       "lottery2024")
PUSH_HOUR   = int(os.environ.get("PUSH_HOUR",   "23"))
PUSH_MINUTE = int(os.environ.get("PUSH_MINUTE", "10"))
TZ = pytz.timezone("Asia/Shanghai")

FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://t.yiqicai.com/"
}

# ========== 微信验证 ==========
@app.route("/wx", methods=["GET", "POST"])
def wx_entry():
    if request.method == "GET":
        signature = request.args.get("signature", "")
        timestamp = request.args.get("timestamp", "")
        nonce     = request.args.get("nonce", "")
        echostr   = request.args.get("echostr", "")
        tmp = "".join(sorted([TOKEN, timestamp, nonce]))
        sha1 = hashlib.sha1(tmp.encode("utf-8")).hexdigest()
        if sha1 == signature:
            return echostr
        return "验证失败", 403
    return "ok"

# ========== 获取 access_token ==========
_token_cache = {"token": "", "expire": 0}

def get_access_token():
    if _token_cache["token"] and time.time() < _token_cache["expire"]:
        return _token_cache["token"]
    url = "https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={}&secret={}".format(APPID, APPSECRET)
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if "access_token" in data:
            _token_cache["token"] = data["access_token"]
            _token_cache["expire"] = time.time() + data["expires_in"] - 300
            print("access_token 获取成功")
            return _token_cache["token"]
        else:
            print("获取token失败: {}".format(data))
    except Exception as e:
        print("请求token异常: {}".format(e))
    return None

# ========== 解析 NUXT 变量映射 ==========
def parse_nuxt_vars(raw):
    var_map = {}
    try:
        func_match = re.search(r'window\.__NUXT__=\(function\(([^)]+)\)', raw)
        if not func_match:
            return var_map
        params = [p.strip() for p in func_match.group(1).split(",")]
        call_match = re.search(r'\}\((.+)\)\s*;?\s*</script>', raw[-30000:], re.DOTALL)
        if not call_match:
            return var_map
        args_raw = call_match.group(1)
        args = []
        depth = 0
        in_str = False
        quote_char = None
        cur = ""
        for ch in args_raw:
            if not in_str and ch in ('"', "'"):
                in_str = True; quote_char = ch; cur += ch
            elif in_str and ch == quote_char:
                in_str = False; cur += ch
            elif not in_str and ch in ('(','[','{'): depth += 1; cur += ch
            elif not in_str and ch in (')',']','}'): depth -= 1; cur += ch
            elif not in_str and ch == ',' and depth == 0:
                args.append(cur.strip()); cur = ""
            else:
                cur += ch
        if cur.strip():
            args.append(cur.strip())
        for i, p in enumerate(params):
            if i < len(args):
                v = args[i]
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                var_map[p] = v
    except Exception as e:
        print("解析NUXT变量失败: {}".format(e))
    return var_map

def resolve(val, var_map):
    """解析字段值：如果是字符串直接返回，否则从变量映射查找"""
    val = val.strip()
    if val.startswith('"') and val.endswith('"'):
        return val[1:-1]
    if val.startswith("'") and val.endswith("'"):
        return val[1:-1]
    return var_map.get(val, "")

# ========== 抓取彩票数据 ==========
def fetch_lottery():
    results = []
    TARGET = ["双色球","大乐透","七星彩","排列五","排列三","福彩3D"]

    try:
        r = requests.get("https://t.yiqicai.com/home/nation", headers=FETCH_HEADERS, timeout=15)
        raw = r.text
        var_map = parse_nuxt_vars(raw)

        # 找所有彩种位置
        positions = [(m.start(), m.group(1)) for m in re.finditer(r'lotteryName:"([^"]+)"', raw)]
        seen = set()

        for i, (pos, name) in enumerate(positions):
            if name not in TARGET or name in seen:
                continue
            seen.add(name)
            end = positions[i+1][0] if i+1 < len(positions) else pos+1000
            block = raw[pos:end]

            def get_str(field):
                m = re.search(r'{}:"([^"]*)"'.format(field), block)
                return m.group(1) if m else ""

            def get_val(field):
                m = re.search(r'{}:([^,}}]+)'.format(field), block)
                if not m:
                    return ""
                return resolve(m.group(1), var_map)

            issue_no   = get_val("issueNo")
            issue_day  = get_val("issueDay")
            issue_week = get_val("issueWeek")
            area1      = get_str("resultArea1")
            area2      = get_str("resultArea2")

            results.append({
                "name": name,
                "issue": issue_no,
                "date": "{} {}".format(issue_day, issue_week).strip(),
                "area1": area1,
                "area2": area2
            })
            print("抓取: {} {}期 {}".format(name, issue_no, issue_day))

    except Exception as e:
        print("一起彩抓取失败: {}".format(e))

    # 双色球用官网补充（更准确）
    try:
        api_r = requests.get(
            "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice?name=ssq&issueCount=1",
            headers={"User-Agent": FETCH_HEADERS["User-Agent"], "Referer": "https://www.cwl.gov.cn/"},
            timeout=10
        )
        d = api_r.json()["result"][0]
        results = [x for x in results if x["name"] != "双色球"]
        results.insert(0, {
            "name": "双色球",
            "issue": d["code"],
            "date": d["date"],
            "area1": d["red"],
            "area2": d["blue"]
        })
        print("双色球官网更新成功")
    except Exception as e:
        print("双色球官网失败: {}".format(e))

    return results

# ========== 格式化消息 ==========
def format_message(lotteries):
    now = datetime.now(TZ)
    date_str = now.strftime("%Y年%m月%d日")
    msg = "🎰 今日开奖结果 {}\n".format(date_str)
    msg += "━━━━━━━━━━━━━━\n"

    order = ["双色球","大乐透","七星彩","排列五","排列三","福彩3D"]
    icons = {"双色球":"🔴","大乐透":"🟡","七星彩":"🔵","排列五":"🟢","排列三":"🟠","福彩3D":"🟣"}
    lmap = {x["name"]: x for x in lotteries}
    has_data = False

    for name in order:
        if name not in lmap:
            continue
        item = lmap[name]
        if not item["area1"]:
            continue
        icon = icons.get(name, "🎯")
        msg += "\n{} {}\n".format(icon, name)
        if item["issue"]:
            msg += "期号：{}期\n".format(item["issue"])
        if item["date"]:
            msg += "开奖：{}\n".format(item["date"])
        if name == "双色球":
            msg += "红球：{}  蓝球：{}\n".format(item["area1"], item["area2"])
        elif name == "大乐透":
            msg += "前区：{}  后区：{}\n".format(item["area1"], item["area2"])
        else:
            msg += "号码：{}\n".format(item["area1"])
        msg += "──────────────\n"
        has_data = True

    if not has_data:
        msg += "\n今日暂无开奖信息，请明日再查。\n"

    msg += "\n📊 走势图：https://t.yiqicai.com/home/nation\n"
    msg += "⚠️ 仅供参考，理性购彩"
    return msg

# ========== 群发推送 ==========
def broadcast(message):
    token = get_access_token()
    if not token:
        print("无法获取token，推送取消")
        return False
    url = "https://api.weixin.qq.com/cgi-bin/message/mass/sendall?access_token={}".format(token)
    payload = {
        "filter": {"is_to_all": True},
        "text": {"content": message},
        "msgtype": "text"
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        result = r.json()
        print("群发结果: {}".format(result))
        return result.get("errcode") == 0
    except Exception as e:
        print("群发异常: {}".format(e))
        return False

# ========== 定时任务 ==========
def scheduled_push():
    now_str = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    print("[{}] 开始定时推送...".format(now_str))
    data = fetch_lottery()
    msg = format_message(data)
    print("推送内容:\n{}".format(msg))
    broadcast(msg)

scheduler = BackgroundScheduler(timezone=TZ)
scheduler.add_job(scheduled_push, "cron", hour=PUSH_HOUR, minute=PUSH_MINUTE)
scheduler.start()

# ========== 路由 ==========
@app.route("/push-now")
def push_now():
    if request.args.get("secret") != "push123":
        return "无权限", 403
    data = fetch_lottery()
    msg = format_message(data)
    broadcast(msg)
    resp = make_response("<pre style='font-size:14px'>{}</pre>".format(msg))
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp

@app.route("/preview")
def preview():
    data = fetch_lottery()
    msg = format_message(data)
    resp = make_response("<pre style='font-size:14px'>{}</pre>".format(msg))
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp

@app.route("/")
def index():
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    return "彩票推送服务运行中 ✅<br>当前时间: {}<br>定时推送: 每天 {:02d}:{:02d} 北京时间".format(
        now, PUSH_HOUR, PUSH_MINUTE)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("服务启动，端口: {}".format(port))
    print("定时推送: 每天 {:02d}:{:02d} 北京时间".format(PUSH_HOUR, PUSH_MINUTE))
    app.run(host="0.0.0.0", port=port)
