# MSB2MIDI
音乐通MITONE机器里的msb文件格式解析成midi
# MSB to MIDI 转换器

将音乐通(MITONE)小提琴陪练机的MSB文件转换为MIDI文件。

## 背景
本程序基于 Jarvis 的逆向分析文章开发：
https://www.jarvisw.com/?p=1132

## MSB文件格式说明
### 文件结构
MSB (MusicScoreBook) 文件采用标签+长度+内容的格式：
```
MSBK                    - Magic头部
├── size (4字节)        - 书本大小
├── type                - 书本类型
├── titl                - 书名
├── auth                - 作者
├── revi                - 版本
├── http                - 网页标题
├── simp                - 简称
├── leve                - 级别
├── cove                - 封面图片(PNG)
└── chap                - 章节信息
    ├── total_chapters  - 总章节数
    └── chapter_offsets - 章节偏移表
```

### 章节结构
每个章节包含：
```
MSCP                    - 章节标签
├── size (4字节)        - 章节大小
├── type                - 类型
├── diff                - 难度
├── enco                - 编码
├── tnnt                - 固定数据
├── inon                - 附加信息
├── titl                - 章节标题
├── auth                - 章节作者
├── midi                - MIDI数据(加密)
└── ovtr                - OVTR数据(加密,自定义乐谱格式)
```

### 加密算法
MIDI和OVTR数据使用简单加密算法：
1. **密钥计算**: 将书名通过hash算法转换为4字节hash值
2. **默认密钥**: 0xee4025cf
3. **解密过程**:
   - 前128字节: 使用密钥进行XOR和减法运算
   - 后续字节: 使用固定密钥序列进行XOR

## 使用方法

### 基本用法
```bash
python msb_to_midi.py <msb文件>
```

### 指定输出目录
```bash
python msb_to_midi.py <msb文件> <输出目录>
```

### 指定解密密钥
```bash
python msb_to_midi.py <msb文件> <输出目录> <密钥(十六进制)>
```

## 示例
```bash
# 转换单个文件
python msb_to_midi.py book.msb

# 指定输出目录
python msb_to_midi.py book.msb ./midi_output

# 使用自定义密钥
python msb_to_midi.py book.msb ./midi_output ee4025cf
```

## 输出
程序会为每个章节生成一个独立的MIDI文件，文件名格式为：

```
<书名>_<章节标题>.mid
```

## 依赖
- Python 3.6+
- 无需额外依赖库(仅使用标准库)

## 注意事项
1. MSB文件中的OVTR格式是厂商自定义的乐谱格式，包含指位提示等信息
2. 本程序仅提取MIDI数据，不处理OVTR格式
3. 如果解密失败，可能需要尝试不同的密钥
4. 密钥通常存储在设备的 `.sn.cfg` 文件中
