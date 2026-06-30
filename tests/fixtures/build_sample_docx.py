"""Build tests/fixtures/csg_sample.docx for doc_parser integration tests."""

from __future__ import annotations

from pathlib import Path

try:
    from docx import Document
except ImportError:
    Document = None  # type: ignore


def build_sample_docx(path: Path) -> Path:
    if Document is None:
        raise ImportError("python-docx required")

    doc = Document()
    doc.add_heading("AFN03 DI=E8000302 查询本地通信模块运行模式信息", level=2)
    doc.add_paragraph("下行请求，无地址域。")

    t1 = doc.add_table(rows=1, cols=3)
    t1.rows[0].cells[0].text = "字段"
    t1.rows[0].cells[1].text = "长度"
    t1.rows[0].cells[2].text = "说明"
    r1 = t1.add_row().cells
    r1[0].text = "local_mode_word"
    r1[1].text = "1字节"
    r1[2].text = "0：路由模式；1：中继模式"

    doc.add_heading("AFN03 DI=E8030304 查询通信延时时长", level=2)
    doc.add_paragraph("下行请求。")

    t2 = doc.add_table(rows=1, cols=3)
    t2.rows[0].cells[0].text = "字段"
    t2.rows[0].cells[1].text = "长度"
    t2.rows[0].cells[2].text = "说明"
    r2 = t2.add_row().cells
    r2[0].text = "dest_addr"
    r2[1].text = "6字节"
    r2[2].text = "通信目的地址"
    r3 = t2.add_row().cells
    r3[0].text = "payload_length"
    r3[1].text = "1字节"
    r3[2].text = "报文长度"

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path


if __name__ == "__main__":
    out = Path(__file__).parent / "csg_sample.docx"
    build_sample_docx(out)
    print(f"written {out}")
