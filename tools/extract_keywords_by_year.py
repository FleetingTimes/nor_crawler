"""
提取指定年份的关键字（批量文本按块解析）

功能概述：
- 从按块分隔的文本（每条记录 5 行：关键字/介绍/URL/时间/类别，后跟一个空行）中筛选“时间行为指定年份”的记录
- 输出命中记录的“关键字”到新文件（一行一个关键字），并在控制台打印统计信息

输入格式：
- 每条记录固定 5 行，之后至少一个空行；例如：
  第1行：关键字（code）
  第2行：介绍（content）
  第3行：URL（detail link）
  第4行：时间（如 2022-01-02 / 2022/01/02 / 2022 年 1 月 2 日 / 仅 2022）
  第5行：类别（文本）
  空行：分隔下一条记录
- 解析会忽略额外空行；不足 5 行的块将被跳过

年份匹配：
- 按“独立年份片段”匹配，支持常见日期格式（YYYY-MM-DD / YYYY/MM/DD / YYYY 年 MM 月 DD 日 / 仅 YYYY）
- 只要时间行中出现独立的目标年份（前后不是数字或到达字符串边界），即视为命中

用法示例：
- Windows/Powershell：
  python extract_keywords_by_year.py "output/AllJavxx_Pages/AllJavxx_Output/data01.txt" "output/AllJavxx_Pages/AllJavxx_Output/keywords_2022.txt" --year 2022 --encoding utf-8
- 参数说明：
  --year      指定年份（默认 2022）
  --encoding  输入/输出文件编码（默认 utf-8）

输出与统计：
- 输出文件：逐行写出命中的关键字；目录不存在会自动创建
- 控制台打印：records_total（总块数）、records_matched（命中块数）、keywords_written（写入关键字数）、output（输出路径）

注意事项：
- 输入文件行尾换行差异（\r\n/\n）已兼容；建议统一使用 utf-8 编码
- 若希望更严格的日期解析（例如只匹配 YYYY-MM-DD），可将 match_year 逻辑替换为更精细的正则或日期解析
"""

import argparse
import os
import re


def parse_records(lines: list[str]) -> list[list[str]]:
    """
    将输入行按“空行分隔”解析为记录块。
    每条记录格式固定为 5 行：
    1. 关键字
    2. 介绍
    3. URL
    4. 时间
    5. 类别
    然后空行，再下一条记录。
    为增强鲁棒性：忽略多余空行，仅当块中有效行数 ≥ 5 时按前 5 行解析。
    """
    records: list[list[str]] = []
    block: list[str] = []
    for raw in lines:
        line = raw.rstrip("\n")
        if line.strip() == "":
            # 遇到空行，提交当前块（如果有内容）
            if block:
                records.append(block)
                block = []
            continue
        block.append(line)
    # 文件末尾可能没有空行，补交最后一块
    if block:
        records.append(block)
    return records


def match_year(time_text: str, year: str) -> bool:
    """
    判断“时间”行是否属于目标年份：
    - 兼容常见格式，如：YYYY-MM-DD、YYYY/MM/DD、YYYY 年 MM 月 DD 日、仅包含 YYYY。
    - 逻辑：只要出现独立的年份片段（边界为非数字或字符串边界），即视为匹配。
    """
    y = re.escape(year)
    return bool(re.search(rf"(^|[^0-9]){y}([^0-9]|$)", time_text))


def extract_keywords(input_path: str, output_path: str, year: str, encoding: str) -> tuple[int, int, int]:
    """
    从输入文件中抽取“时间为指定年份”的记录的关键字，写入输出文件（每行一个关键字）。
    返回统计信息：(总记录数, 命中记录数, 输出关键字数)
    """
    with open(input_path, "r", encoding=encoding, errors="ignore") as f:
        lines = f.readlines()

    records = parse_records(lines)
    total = len(records)
    hits = 0
    out_count = 0

    # 确保输出目录存在
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(output_path, "w", encoding=encoding) as out:
        for block in records:
            if len(block) < 5:
                # 跳过不完整记录
                continue
            keyword = (block[0] or "").strip()
            time_text = (block[3] or "").strip()
            if match_year(time_text, year):
                hits += 1
                if keyword:
                    out.write(keyword + "\n")
                    out_count += 1

    return total, hits, out_count


def main():
    parser = argparse.ArgumentParser(
        prog="extract_keywords_by_year",
        description="从按块分隔的文本中抽取指定年份(时间行)对应的关键字"
    )
    parser.add_argument("input", help="输入文件路径（如 data01.txt）")
    parser.add_argument("output", help="输出关键字文件路径（新建或覆盖）")
    parser.add_argument("--year", default="2022", help="目标年份，默认 2022")
    parser.add_argument("--encoding", default="utf-8", help="文件编码，默认 utf-8")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        raise SystemExit(f"输入文件不存在: {args.input}")

    total, hits, out_count = extract_keywords(args.input, args.output, args.year, args.encoding)
    print(f"records_total={total} records_matched={hits} keywords_written={out_count} output={args.output}")


if __name__ == "__main__":
    main()

