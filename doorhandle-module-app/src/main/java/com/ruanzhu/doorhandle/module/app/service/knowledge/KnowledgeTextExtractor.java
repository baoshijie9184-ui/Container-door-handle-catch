package com.ruanzhu.doorhandle.module.app.service.knowledge;

import com.ruanzhu.doorhandle.common.BusinessException;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.text.PDFTextStripper;
import org.apache.poi.xwpf.usermodel.XWPFDocument;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.apache.poi.xslf.usermodel.XMLSlideShow;
import org.apache.poi.xslf.usermodel.XSLFTextShape;
import org.apache.poi.ss.usermodel.DataFormatter;
import org.springframework.stereotype.Component;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.charset.*;
import java.util.*;
import java.util.concurrent.Semaphore;
import java.util.zip.ZipInputStream;

/** Bounded text-only indexing. Never execute Office macros, formulas, links, or embedded instructions. */
@Component
public class KnowledgeTextExtractor {
    public record Text(String content, String mediaType) { }
    private static final int MAX_TEXT = 200_000;
    private static final Semaphore PARSERS = new Semaphore(2);

    public Text extract(String filename, byte[] bytes) {
        if (bytes.length == 0 || bytes.length > 5 * 1024 * 1024) throw fail(413, "资料须为 1 字节至 5 MiB");
        String suffix = filename.substring(filename.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT);
        if (!Set.of("txt", "md", "csv", "json", "pdf", "docx", "xlsx", "pptx").contains(suffix)) throw fail(415, "支持 TXT、Markdown、CSV、JSON、PDF、DOCX、XLSX 和 PPTX");
        if (!PARSERS.tryAcquire()) throw fail(429, "资料解析繁忙，请稍后重试");
        try {
            StringBuilder text = new StringBuilder();
            if (Set.of("txt", "md", "csv", "json").contains(suffix)) {
                String value = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
                if (value.codePoints().anyMatch(c -> c < 32 && c != '\n' && c != '\r' && c != '\t' && c != '\f')) throw fail(415, "资料包含二进制控制字符");
                append(text, value);
            } else if (suffix.equals("pdf")) {
                try (var pdf = Loader.loadPDF(bytes)) {
                    if (pdf.isEncrypted() || !pdf.getCurrentAccessPermission().canExtractContent() || pdf.getNumberOfPages() > 100) throw fail(415, "PDF 须允许提取文字，且不超过 100 页");
                    var stripper = new PDFTextStripper() {
                        private int operations, glyphs;
                        @Override protected void processOperator(org.apache.pdfbox.contentstream.operator.Operator operation, List<org.apache.pdfbox.cos.COSBase> operands) throws IOException { if (++operations > 200_000) throw fail(413,"PDF 内容操作超出解析上限"); super.processOperator(operation,operands); }
                        @Override protected void processTextPosition(org.apache.pdfbox.text.TextPosition position) { if (++glyphs > MAX_TEXT) throw fail(413,"PDF 文字数量超出索引上限"); super.processTextPosition(position); }
                    };
                    for (int page = 1; page <= pdf.getNumberOfPages(); page++) {
                        stripper.setStartPage(page); stripper.setEndPage(page);
                        append(text, "\n[第 " + page + " 页]\n");
                        stripper.writeText(pdf,new Writer(){@Override public void write(char[] chars,int offset,int length){KnowledgeTextExtractor.append(text,new String(chars,offset,length));}@Override public void flush(){}@Override public void close(){}});
                    }
                }
            } else {
                boundedZip(bytes);
                if (suffix.equals("docx")) try (var doc = new XWPFDocument(new ByteArrayInputStream(bytes))) {
                    for (var element : doc.getBodyElements()) {
                        if(element instanceof org.apache.poi.xwpf.usermodel.XWPFParagraph paragraph)append(text,paragraph.getText()+"\n");
                        else if(element instanceof org.apache.poi.xwpf.usermodel.XWPFTable table)for(var row:table.getRows()){for(var cell:row.getTableCells())append(text,cell.getText()+"\t");append(text,"\n");}
                    }
                } else if (suffix.equals("xlsx")) try (var workbook = new XSSFWorkbook(new ByteArrayInputStream(bytes))) {
                    var formatter = new DataFormatter(); formatter.setUseCachedValuesForFormulaCells(true);
                    int cells = 0;
                    for (var sheet : workbook) {
                        append(text, "\n[工作表 " + sheet.getSheetName() + "]\n");
                        for (var row : sheet) { for (var cell : row) { if (++cells > 20_000) throw fail(413, "表格超过 20,000 个单元格，请拆分");String value=formatter.formatCellValue(cell);if(cell.getCellType()==org.apache.poi.ss.usermodel.CellType.FORMULA)value=cell instanceof org.apache.poi.xssf.usermodel.XSSFCell source&&!source.getCTCell().isSetV()?"[公式，无缓存结果]":"[公式缓存]"+value;append(text, cell.getAddress().formatAsString()+"："+value + "\t"); } append(text, "\n"); }
                    }
                } else try (var slides = new XMLSlideShow(new ByteArrayInputStream(bytes))) {
                    if (slides.getSlides().size() > 100) throw fail(413, "演示文稿不超过 100 页");
                    int page = 0;
                    for (var slide : slides.getSlides()) { append(text, "\n[幻灯片 " + ++page + "]\n"); for (var shape : slide.getShapes()) {if (shape instanceof XSLFTextShape value) append(text, value.getText() + "\n");else if(shape instanceof org.apache.poi.xslf.usermodel.XSLFTable table)for(var row:table.getRows()){for(var cell:row.getCells())append(text,cell.getText()+"\t");append(text,"\n");}} }
                }
            }
            String content = text.toString().strip();
            if (content.replaceAll("\\[(?:第 \\d+ 页|工作表 [^]]*|幻灯片 \\d+)]", "").isBlank()) throw fail(422, "未提取到文字。扫描件和图片需要 OCR 后再导入");
            return new Text(content, suffix.equals("pdf") ? "application/pdf" : "text/" + suffix);
        } catch (BusinessException error) { throw error;
        } catch (IOException | RuntimeException error) { throw fail(415, "资料无法读取，请检查文件格式、加密状态及 UTF-8 编码");
        } finally { PARSERS.release(); }
    }

    private static void boundedZip(byte[] bytes) throws IOException {
        try (var zip = new ZipInputStream(new ByteArrayInputStream(bytes))) {
            byte[] buffer = new byte[8192]; long total = 0; int entries = 0;
            for (var entry = zip.getNextEntry(); entry != null; entry = zip.getNextEntry()) {
                if (++entries > 2000 || entry.getName().toLowerCase(Locale.ROOT).contains("vbaproject")) throw fail(415, "不接收宏或超出结构限制的 Office 文件");
                int read; while ((read = zip.read(buffer)) >= 0) { total += read; if (total > 20L * 1024 * 1024) throw fail(413, "Office 解压内容超过 20 MiB"); }
            }
            if (entries == 0) throw fail(415, "不是有效的 Office 文件");
        }
    }
    private static void append(StringBuilder target, String value) { if (value.length() > MAX_TEXT - target.length()) throw fail(413, "提取文字超过 20 万字符，请拆分文档"); target.append(value); }
    private static BusinessException fail(int status, String message) { return new BusinessException(status, message); }
}
