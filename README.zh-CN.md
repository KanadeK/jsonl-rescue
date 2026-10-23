# jsonl-rescue 中文说明

本地处理 JSONL 导入失败：将正常记录与异常记录按原始字节分流，保存偏移日志，
之后校验 SHA-256 并恢复完全一致的原文件。不会自动修复或静默丢弃异常数据。

需要 Python 3.11+，没有运行时依赖。在源码目录创建并激活虚拟环境后运行：

```console
python -m pip install .
python scripts/demo.py
jsonl-rescue split incoming.jsonl --output recovery
jsonl-rescue reassemble recovery --output original-copy.bin
```

输出必须是不存在的新路径。分流成功但含异常记录时退出码为 1；无异常或重组成功为 0；
输入、I/O 或校验错误为 2。默认单条记录上限为 1 MiB（包含换行），超长记录以固定大小
块写入隔离文件。支持 LF、CRLF 和末行缺少换行；拒绝重复键、非有限数、BOM、空行等。

隔离目录中的两个数据文件仍含原始内容，请按原数据的保密等级保管。日志和终端摘要
不回显记录值。校验哈希不等于数字签名。当前不支持恢复中断任务、JSON Schema 或压缩输入，
也不保证断电后的持久性。

卸载：`python -m pip uninstall jsonl-rescue`。自行删除不再需要的输出目录即可清理。
完整规则、测试命令和限制见 [English README](README.md)。MIT 许可证。
