"""
文本关键字交集比较工具

功能概述：
- 比较两个文本文件中的关键字，输出两者的重复项（交集），每行一个关键字。
- 关键字来源：默认每行一个关键字；如指定分隔符（--sep），则按该分隔符将每行切分为多个关键字。

输入与解析：
- file1、file2：待比较的两个文本文件路径。
- 行解析：
  - 默认：整行作为一个关键字；空行与纯空白行忽略。
  - 指定分隔符：例如 --sep ","，则每行按逗号切分为多个关键字，去除每个片段的首尾空白后加入集合。
- 大小写：默认不区分大小写（统一转为小写）；如需区分大小写，传入 --case-sensitive。

输出：
- output：写出两文件关键字交集的结果文件；若目录不存在将自动创建。
- 控制台打印统计：file1_keywords / file2_keywords / duplicates / output。

使用示例：
1) 按行比较（不区分大小写）：
   python compare_file.py a.txt b.txt out.txt
2) 指定分隔符，并区分大小写：
   python compare_file.py a.txt b.txt out.txt --sep "," --case-sensitive
3) 指定编码（默认 utf-8）：
   python compare_file.py a.txt b.txt out.txt --encoding gbk

注意事项：
- 文件编码建议统一为 utf-8；如源文件编码不同，使用 --encoding 指定。
- 当使用 --case-sensitive 时，大小写完全匹配才视为重复；关闭时 "ABC" 与 "abc" 视为同一关键字。
"""

import argparse
import os

def read_keywords(path: str, sep: str | None, case_sensitive: bool, encoding: str) -> set[str]:
    items: set[str] = set()
    with open(path, "r", encoding=encoding, errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if sep:
                parts = [p.strip() for p in line.split(sep)]
            else:
                parts = [line]
            for p in parts:
                if not p:
                    continue
                items.add(p if case_sensitive else p.lower())
    return items

def main():
    parser = argparse.ArgumentParser(prog="compare_file", description="Compare two text files and output duplicate keywords")
    parser.add_argument("file1", help="First text file path")
    parser.add_argument("file2", help="Second text file path")
    parser.add_argument("output", help="Output file path for duplicates")
    parser.add_argument("--sep", default=None, help="Delimiter to split each line into keywords; default per-line")
    parser.add_argument("--encoding", default="utf-8", help="File encoding, default utf-8")
    parser.add_argument("--case-sensitive", action="store_true", help="Enable case-sensitive comparison")
    args = parser.parse_args()

    if not os.path.exists(args.file1):
        raise SystemExit(f"Input not found: {args.file1}")
    if not os.path.exists(args.file2):
        raise SystemExit(f"Input not found: {args.file2}")

    s1 = read_keywords(args.file1, args.sep, args.case_sensitive, args.encoding)
    s2 = read_keywords(args.file2, args.sep, args.case_sensitive, args.encoding)
    dup = sorted(s1.intersection(s2))

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
    with open(args.output, "w", encoding=args.encoding) as out:
        for k in dup:
            out.write(f"{k}\n")

    print(f"file1_keywords={len(s1)} file2_keywords={len(s2)} duplicates={len(dup)} output={args.output}")

if __name__ == "__main__":
    main()

