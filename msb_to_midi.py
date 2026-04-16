#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
MSB to MIDI Converter
将音乐通(MITONE)小提琴陪练机的MSB文件转换为MIDI文件

基于 https://www.jarvisw.com/?p=1132 的逆向分析结果
"""

import struct
import os
import sys
from pathlib import Path


def int32_ror(x, k):
    """32位整数循环右移"""
    x = x & 0xFFFFFFFF
    if k < 0:
        # 负数表示左移
        k = -k % 32
        return ((x << k) | (x >> (32 - k))) & 0xFFFFFFFF
    else:
        k = k % 32
        return ((x >> k) | (x << (32 - k))) & 0xFFFFFFFF


def calc_book_hash(bookname):
    """计算书本名称的hash值"""
    booklen = len(bookname)
    hash_val = booklen
    for ch in bookname:
        data = ord(ch)
        if data & 0x80 != 0:
            data = 0xffffff00 | data
        hash_val = int32_ror(hash_val, -27) ^ data
    return hash_val


def data_dec_last_part(data, length):
    """解密数据的最后部分"""
    if length <= 0:
        return b''
    
    v4 = (length + 3) & 0xFFFFFFFC
    ret = bytearray(data)
    idx = 0
    
    while idx < v4:
        ret[idx] ^= 0x5F
        ret[idx + 1] ^= 0xE3
        ret[idx + 2] ^= 0x1D
        ret[idx + 3] ^= 0xAC
        idx += 4
    
    # 处理剩余字节
    while idx < length:
        xor_keys = [0x5F, 0xE3, 0x1D, 0xAC]
        ret[idx] ^= xor_keys[idx % 4]
        idx += 1
    
    return bytes(ret)


def midi_decode(data, key):
    """解密MIDI数据"""
    length = len(data)
    if length == 0:
        return b''
    
    key2 = (key - 0x7B8C754D) & 0xFFFFFFFF
    
    if length <= 127:
        # 短数据处理
        v9 = (length + 3) & 0xFFFFFFFC
        v7 = (key2 * key) & 0xFFFFFFFF
        v11 = (v7 + 0x5483B7FD) & 0xFFFFFFFF
        v14 = v11
        
        ret = []
        idx = 0
        while idx < v9:
            ret.append(struct.unpack("<I", data[idx:idx + 4])[0])
            idx += 4
        
        v10 = 0
        v13 = 0
        v12 = v9 >> 2
        while v13 < v12:
            v15 = (ret[v10] - v14) & 0xFFFFFFFF
            v14 = (v14 + v11) & 0xFFFFFFFF
            ret[v10] = v15 ^ 0x5483B7FD
            v10 += 1
            v13 += 1
        
        result = b''
        for val in ret:
            result += struct.pack("<I", val)
        return result
    else:
        # 长数据处理 (超过127字节)
        ret = []
        idx = 0
        while idx < 128:
            ret.append(struct.unpack("<I", data[idx:idx + 4])[0])
            idx += 4
        
        for i in range(32):
            ret[i] = ((ret[i] - key2) & 0xFFFFFFFF) ^ 0xAAAAAAAA
        
        result = b''
        for val in ret:
            result += struct.pack("<I", val)
        
        result += data_dec_last_part(data[128:], length - 128)
        return result


def sn_decode_ovh(data, key):
    """解密OVH数据的特殊部分"""
    length = len(data)
    if length == 0:
        return b''
    
    v5 = 0x8D23B1B
    ret = []
    idx = 0
    
    while idx < length:
        ret.append(struct.unpack("<I", data[idx:idx + 4])[0])
        idx += 4
    
    for i in range(len(ret)):
        ret[i] = ((ret[i] - v5) & 0xFFFFFFFF) ^ 0x5483B7FD
        v5 = (v5 + 0x8D23B1B) & 0xFFFFFFFF
    
    result = b''
    for val in ret:
        result += struct.pack("<I", val)
    
    return result


def ovh_decode(data, key):
    """解密OVTR/OVH数据"""
    length = len(data)
    if length == 0:
        return b''
    
    if length <= 127:
        v10 = (length + 3) & 0xFFFFFFFC
        return sn_decode_ovh(data[:v10], key)
    else:
        result = sn_decode_ovh(data[:128], key)
        result += data_dec_last_part(data[128:], length - 128)
        return result


def read_string(data, offset):
    """读取标签字符串"""
    if offset + 4 > len(data):
        return None, offset
    return data[offset:offset + 4].decode('latin-1'), offset + 4


def read_uint32(data, offset):
    """读取4字节无符号整数"""
    if offset + 4 > len(data):
        return 0, offset
    return struct.unpack("<I", data[offset:offset + 4])[0], offset + 4


def read_length_and_data(data, offset):
    """读取长度和数据，处理4字节对齐填充"""
    if offset + 4 > len(data):
        return None, offset
    length = struct.unpack("<I", data[offset:offset + 4])[0]
    offset += 4
    if offset + length > len(data):
        return None, offset
    result = data[offset:offset + length]
    offset += length
    # 处理4字节对齐填充
    padding = (4 - (length % 4)) % 4
    offset += padding
    return result, offset


class MSBParser:
    """MSB文件解析器"""
    
    def __init__(self, filepath, key=None):
        self.filepath = filepath
        self.key = key if key else 0xee4025cf  # 默认key
        self.data = None
        self.book_info = {}
        self.chapters = []
    
    def parse(self):
        """解析MSB文件"""
        with open(self.filepath, 'rb') as f:
            self.data = f.read()
        
        offset = 0
        
        # 读取Magic
        magic, offset = read_string(self.data, offset)
        if magic != 'MSBK':
            raise ValueError(f"Invalid MSB file: expected 'MSBK', got '{magic}'")
        
        # 读取书本大小
        book_size, offset = read_uint32(self.data, offset)
        self.book_info['size'] = book_size
        
        # 解析书本头部
        while offset < len(self.data):
            label, offset = read_string(self.data, offset)
            if not label:
                break
            
            if label == 'TYPE':
                value, offset = read_uint32(self.data, offset)
                self.book_info['type'] = value
            
            elif label == 'TITL':
                title_data, offset = read_length_and_data(self.data, offset)
                if title_data:
                    self.book_info['title'] = title_data.decode('gbk', errors='ignore')
            
            elif label == 'AUTH':
                author_data, offset = read_length_and_data(self.data, offset)
                if author_data:
                    self.book_info['author'] = author_data.decode('gbk', errors='ignore')
            
            elif label == 'REVI':
                rev_data, offset = read_length_and_data(self.data, offset)
                if rev_data:
                    self.book_info['revision'] = rev_data.decode('gbk', errors='ignore')
            
            elif label == 'HTTP':
                http_data, offset = read_length_and_data(self.data, offset)
                if http_data:
                    self.book_info['http_title'] = http_data.decode('gbk', errors='ignore')
            
            elif label == 'SIMP':
                simp_data, offset = read_length_and_data(self.data, offset)
                if simp_data:
                    self.book_info['simple_name'] = simp_data.decode('gbk', errors='ignore')
            
            elif label == 'LEVL':
                level_data, offset = read_length_and_data(self.data, offset)
                if level_data:
                    self.book_info['level'] = level_data.decode('gbk', errors='ignore')
            
            elif label == 'COVE':
                cover_data, offset = read_length_and_data(self.data, offset)
                if cover_data:
                    self.book_info['cover'] = cover_data
            
            elif label == 'CHAP':
                # 章节信息
                total_chapters, offset = read_uint32(self.data, offset)
                self.book_info['total_chapters'] = total_chapters
                
                # 读取章节偏移表
                chapter_offsets = []
                for _ in range(total_chapters):
                    chap_offset, offset = read_uint32(self.data, offset)
                    chapter_offsets.append(chap_offset)
                
                self.book_info['chapter_offsets'] = chapter_offsets
                
                # 解析每个章节
                for i, chap_offset in enumerate(chapter_offsets):
                    chapter = self.parse_chapter(chap_offset, i + 1)
                    if chapter:
                        self.chapters.append(chapter)
                break
            
            else:
                # 跳过未知标签
                length, offset = read_uint32(self.data, offset)
                offset += length
        
        return self
    
    def parse_chapter(self, offset, chapter_num):
        """解析单个章节"""
        chapter = {
            'number': chapter_num,
            'midi_data': None,
            'ovtr_data': None
        }
        
        # 读取章节标签
        label, offset = read_string(self.data, offset)
        if label != 'MSCP':
            return None
        
        # 读取章节大小
        chap_size, offset = read_uint32(self.data, offset)
        
        # 解析章节内容
        while offset < len(self.data):
            label, offset = read_string(self.data, offset)
            if not label:
                break
            
            if label == 'TYPE':
                value, offset = read_uint32(self.data, offset)
                chapter['type'] = value
            
            elif label == 'DIFF':
                value, offset = read_uint32(self.data, offset)
                chapter['difficulty'] = value
            
            elif label == 'ENCO':
                value, offset = read_uint32(self.data, offset)
                chapter['encoding'] = value
            
            elif label == 'TNNT':
                # 4字节固定数据
                if offset + 4 <= len(self.data):
                    chapter['tnnt'] = self.data[offset:offset + 4]
                    offset += 4
            
            elif label == 'INON':
                data, offset = read_length_and_data(self.data, offset)
                if data:
                    chapter['inon'] = data
            
            elif label == 'TITL':
                data, offset = read_length_and_data(self.data, offset)
                if data:
                    chapter['title'] = data.decode('gbk', errors='ignore')
            
            elif label == 'AUTH':
                data, offset = read_length_and_data(self.data, offset)
                if data:
                    chapter['author'] = data.decode('gbk', errors='ignore')
            
            elif label == 'MIDI':
                # MIDI数据 (加密)
                data, offset = read_length_and_data(self.data, offset)
                if data:
                    chapter['midi_data_encrypted'] = data
                    # 解密MIDI数据
                    chapter['midi_data'] = midi_decode(data, self.key)
            
            elif label == 'OVTR':
                # OVTR数据 (加密)
                data, offset = read_length_and_data(self.data, offset)
                if data:
                    chapter['ovtr_data_encrypted'] = data
                    # 解密OVTR数据
                    chapter['ovtr_data'] = ovh_decode(data, self.key)
            
            else:
                # 跳过未知标签
                length, offset = read_uint32(self.data, offset)
                offset += length
                
                # 如果遇到下一个章节标签，停止
                if label == 'MSCP':
                    break
        
        return chapter
    
    def extract_midi(self, output_dir=None):
        """提取所有MIDI文件"""
        if output_dir is None:
            output_dir = os.path.dirname(self.filepath)
        
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        book_title = self.book_info.get('title', 'Unknown')
        extracted_files = []
        
        for chapter in self.chapters:
            if chapter.get('midi_data'):
                # 生成文件名
                chapter_title = chapter.get('title', f"Chapter_{chapter['number']}")
                # 清理文件名中的非法字符和特殊字符
                safe_title = ""
                for c in chapter_title:
                    if c.isalnum() or c in (' ', '-', '_', '(', ')'):
                        safe_title += c
                    elif '\u4e00' <= c <= '\u9fff':  # 中文字符
                        safe_title += c
                safe_title = safe_title.strip()
                if not safe_title:
                    safe_title = f"Chapter_{chapter['number']}"
                
                # 书名也清理
                safe_book = ""
                for c in book_title:
                    if c.isalnum() or c in (' ', '-', '_', '(', ')'):
                        safe_book += c
                    elif '\u4e00' <= c <= '\u9fff':
                        safe_book += c
                safe_book = safe_book.strip() if safe_book.strip() else "Book"
                
                filename = f"{safe_book}_{safe_title}.mid"
                
                filepath = output_dir / filename
                
                # 写入MIDI文件
                with open(filepath, 'wb') as f:
                    f.write(chapter['midi_data'])
                
                extracted_files.append(str(filepath))
                try:
                    print(f"已提取: {filepath}")
                except UnicodeEncodeError:
                    print(f"已提取: {str(filepath).encode('gbk', errors='replace').decode('gbk')}")
        
        return extracted_files
    
    def safe_print(self, text):
        """安全打印，处理编码问题"""
        try:
            print(text)
        except UnicodeEncodeError:
            # 过滤无法编码的字符
            safe_text = text.encode('gbk', errors='replace').decode('gbk')
            print(safe_text)
    
    def print_info(self):
        """打印书本信息"""
        self.safe_print("\n" + "=" * 60)
        self.safe_print("MSB文件信息")
        self.safe_print("=" * 60)
        self.safe_print(f"文件: {self.filepath}")
        self.safe_print(f"书名: {self.book_info.get('title', 'N/A')}")
        self.safe_print(f"作者: {self.book_info.get('author', 'N/A')}")
        self.safe_print(f"版本: {self.book_info.get('revision', 'N/A')}")
        self.safe_print(f"级别: {self.book_info.get('level', 'N/A')}")
        self.safe_print(f"总章节数: {self.book_info.get('total_chapters', 0)}")
        self.safe_print(f"解密密钥: 0x{self.key:08X}")
        
        if self.chapters:
            self.safe_print("\n章节列表:")
            self.safe_print("-" * 60)
            for chapter in self.chapters:
                title = chapter.get('title', 'N/A')
                has_midi = "Yes" if chapter.get('midi_data') else "No"
                has_ovtr = "Yes" if chapter.get('ovtr_data') else "No"
                self.safe_print(f"  第{chapter['number']}章: {title}")
                self.safe_print(f"    MIDI: {has_midi}  OVTR: {has_ovtr}")
        
        self.safe_print("=" * 60 + "\n")


def convert_msb_to_midi(msb_file, output_dir=None, key=None):
    """
    将MSB文件转换为MIDI文件
    
    参数:
        msb_file: MSB文件路径
        output_dir: 输出目录(可选,默认为MSB文件所在目录)
        key: 解密密钥(可选,默认为0xee4025cf)
    
    返回:
        提取的MIDI文件列表
    """
    parser = MSBParser(msb_file, key)
    parser.parse()
    parser.print_info()
    return parser.extract_midi(output_dir)


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python msb_to_midi.py <msb文件> [输出目录] [密钥(十六进制)]")
        print("\n示例:")
        print("  python msb_to_midi.py book.msb")
        print("  python msb_to_midi.py book.msb ./output")
        print("  python msb_to_midi.py book.msb ./output ee4025cf")
        sys.exit(1)
    
    msb_file = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    key = int(sys.argv[3], 16) if len(sys.argv) > 3 else None
    
    if not os.path.exists(msb_file):
        print(f"错误: 文件不存在 - {msb_file}")
        sys.exit(1)
    
    try:
        extracted = convert_msb_to_midi(msb_file, output_dir, key)
        print(f"\n成功提取 {len(extracted)} 个MIDI文件")
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
