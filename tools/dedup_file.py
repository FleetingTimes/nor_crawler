"""
单文件关键字去重工具

功能概述：
- 读取一个文本文件（每行一个关键字），去除重复关键字后写出到目标文件；默认保留首次出现的顺序。

输入与选项：
- input：待处理的文本文件路径（必填）。
- --output：输出文件路径；未提供时默认生成同目录下的 `<原名>.dedup.txt`。
- --inplace：就地覆盖原文件（谨慎使用，与 --output 互斥）。
- --case-sensitive：大小写敏感；默认不敏感（统一转小写进行去重）。
- --encoding：文件编码，默认 `utf-8`。
- --strip-empty：去除空行；默认保留空行但不会参与去重。

行为细节：
- 默认“大小写不敏感”意味着 `ABC` 与 `abc` 视为同一关键字；开启 --case-sensitive 则区分。
- 去重基于“首次出现优先”，因此输出维持原始出现顺序（稳定去重）。
- 读写异常（例如路径不存在/权限不足）会给出友好错误说明并退出。

使用示例：
1) 基本去重（不区分大小写，保留顺序）：
   python dedup_file.py keywords.txt
2) 指定输出路径并区分大小写：
   python dedup_file.py keywords.txt --output out.txt --case-sensitive
3) 覆盖原文件（谨慎）：
   python dedup_file.py keywords.txt --inplace

注意：
- 若与现有脚本 compare_file.py 联合使用，compare_file.py 偏重“交集比较”，本工具专注“单文件稳定去重”。
"""

from __future__ import annotations

import argparse
import os
import sys


def dedup_lines(path: str, case_sensitive: bool, encoding: str, strip_empty: bool) -> list[str]:
    """
    读取指定文本文件并进行稳定去重：
    - 稳定：保留每个关键字首次出现时的相对顺序；后续重复项被忽略。
    - 大小写：默认不敏感；敏感时直接使用原文本作为唯一性键。
    - 空行：默认保留，但不参与去重；开启 strip_empty 时直接丢弃空行。

    返回值为“去重后的行列表”（不含末尾换行符）。
    """
    seen: set[str] = set()  # 存放已见过的唯一性键（大小写处理后的值）
    result: list[str] = []  # 收集输出的行（按原始顺序）

    # 以忽略错误模式打开，避免个别不可解码字符导致整体失败；
    # 若需要严格解码，可去掉 errors="ignore" 并调整编码参数。
    with open(path, "r", encoding=encoding, errors="ignore") as f:
        for line in f:
            # 保留原始行的主体内容，不含换行符
            raw = line.rstrip("\n\r")
            txt = raw.strip()

            # 空行处理：默认保留到结果，但不参与去重集合；strip_empty 时直接跳过
            if not txt:
                if not strip_empty:
                    result.append(raw)
                continue

            # 唯一性键：大小写不敏感时统一转为小写；否则使用原文本
            key = txt if case_sensitive else txt.lower()
            if key in seen:
                # 跳过重复项（保持首次出现的稳定性）
                continue
            seen.add(key)
            # 保留原始行（含原始空白与大小写），便于与原文件风格一致
            result.append(raw)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(prog="dedup_file", description="Remove duplicate keywords from a single text file")
    parser.add_argument("input", help="Input text file path (one keyword per line)")
    parser.add_argument("--output", default=None, help="Output file path; default <input>.dedup.txt")
    parser.add_argument("--inplace", action="store_true", help="Overwrite the input file (mutually exclusive with --output)")
    parser.add_argument("--case-sensitive", action="store_true", help="Enable case-sensitive deduplication")
    parser.add_argument("--encoding", default="utf-8", help="File encoding, default utf-8")
    parser.add_argument("--strip-empty", action="store_true", help="Remove empty lines instead of keeping them")
    args = parser.parse_args()

    in_path = args.input
    if not os.path.exists(in_path):
        print(f"Input not found: {in_path}")
        return 2

    # 处理输出目标：
    # - 指定 --inplace 时覆盖原文件；
    # - 指定 --output 时写到目标；
    # - 两者都未指定时默认生成 <input>.dedup.txt。
    if args.inplace and args.output:
        print("Cannot use --inplace and --output together. Choose one.")
        return 2

    if args.inplace:
        out_path = in_path
    else:
        if args.output:
            out_path = args.output
        else:
            root, ext = os.path.splitext(os.path.abspath(in_path))
            out_path = f"{root}.dedup{ext or '.txt'}"

    # 执行稳定去重
    deduped = dedup_lines(in_path, case_sensitive=args.case_sensitive, encoding=args.encoding, strip_empty=args.strip_empty)

    # 写出文件（确保目录存在）
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding=args.encoding) as f:
        for ln in deduped:
            f.write(ln + "\n")

    # 控制台统计信息（便于确认结果）
    print(
        """
Dedup completed.
- input: {inp}
- output: {out}
- case_sensitive: {cs}
- strip_empty: {se}
- lines_out: {cnt}
""".strip().format(
            inp=in_path,
            out=out_path,
            cs=bool(args.case_sensitive),
            se=bool(args.strip_empty),
            cnt=len(deduped),
        )
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())