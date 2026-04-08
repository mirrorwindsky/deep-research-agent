# 文件路径：tools/weather.py

def get_weather(location: str) -> str:
    """
    这是一个本地的 Python 函数。
    在真实项目中，这里会去调用真实的天气 API，比如和风天气。
    现在我们用模拟数据代替。
    """
    print(f"⚙️ [本地工具执行] 正在查询 {location} 的天气...")
    if "北京" in location:
        return "晴天，25度，微风"
    elif "伦敦" in location:
        return "下大雨，12度"
    else:
        return "多云，20度"