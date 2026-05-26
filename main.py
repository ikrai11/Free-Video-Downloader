# 获取当前天气
import json
import ssl
import urllib.request
import urllib.parse


def get_weather(city="北京"):
    """获取指定城市的当前天气（使用 wttr.in 免费 API，无需 API Key）"""
    url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, headers={"User-Agent": "curl/7.0"})
    with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
        data = json.loads(resp.read().decode())

    current = data["current_condition"][0]
    return {
        "city": city,
        "temperature": current["temp_C"] + "°C",
        "feels_like": current["FeelsLikeC"] + "°C",
        "weather": current["weatherDesc"][0]["value"],
        "humidity": current["humidity"] + "%",
        "wind_speed": current["windspeedKmph"] + " km/h",
    }


if __name__ == "__main__":
    city = input("请输入要查询的城市（直接回车默认 北京）：").strip()
    if not city:
        city = "北京"

    try:
        weather = get_weather(city)
        print(f"\n{weather['city']}天气：")
        print(f"  温度: {weather['temperature']}（体感 {weather['feels_like']}）")
        print(f"  天气: {weather['weather']}")
        print(f"  湿度: {weather['humidity']}")
        print(f"  风速: {weather['wind_speed']}")
    except Exception as e:
        print(f"查询失败：{e}")
