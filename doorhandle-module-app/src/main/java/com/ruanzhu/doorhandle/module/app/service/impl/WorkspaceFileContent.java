package com.ruanzhu.doorhandle.module.app.service.impl;

import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.StreamReadConstraints;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.contentstream.operator.Operator;
import org.apache.pdfbox.cos.COSBase;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.text.PDFTextStripper;
import org.apache.pdfbox.text.TextPosition;
import org.apache.pdfbox.rendering.PDFRenderer;
import org.apache.pdfbox.rendering.ImageType;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import javax.imageio.ImageIO;
import javax.imageio.ImageReader;
import javax.imageio.stream.MemoryCacheImageInputStream;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.Writer;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.Semaphore;

/** 工作区私有文件的解析边界；调用者须先完成账号、会话与文件摘要校验。 */
final class WorkspaceFileContent {
    static final int MAX_PDF_PAGES = 100;
    static final long MAX_IMAGE_PIXELS = 16_000_000;
    static final String TRUNCATED = "\n[内容已按预览上限截断，请勿将此片段视为完整文件]";
    private static final Semaphore PARSERS = new Semaphore(2);
    private static final ObjectMapper JSON = new ObjectMapper(JsonFactory.builder().streamReadConstraints(
            StreamReadConstraints.builder().maxNestingDepth(100).maxStringLength(1_000_000).maxNumberLength(1000).build()).build())
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);

    private WorkspaceFileContent() {}

    record PdfPreview(byte[] png, int page, int pages) {}

    static PdfPreview previewPdf(byte[] bytes, int page) {
        if (page < 1 || page > MAX_PDF_PAGES) throw fail(400, "PDF 页码无效");
        acquire();
        try (PDDocument document = pdf(bytes)) {
            checkPdf(document);
            int pages = document.getNumberOfPages();
            if (page > pages) throw fail(400, "PDF 页码超出文档范围");
            var box = document.getPage(page - 1).getCropBox();
            if (!Float.isFinite(box.getWidth()) || !Float.isFinite(box.getHeight()) || box.getWidth() <= 0 || box.getHeight() <= 0)
                throw fail(415, "PDF 页面尺寸无效");
            float scale = Math.min(2f, Math.min(1400f / box.getWidth(), 1800f / box.getHeight()));
            var renderer = new PDFRenderer(document);
            renderer.setSubsamplingAllowed(true);
            var image = renderer.renderImage(page - 1, scale, ImageType.RGB);
            try (var output = new ByteArrayOutputStream()) {
                ImageIO.write(image, "png", output);
                return new PdfPreview(output.toByteArray(), page, pages);
            } finally { image.flush(); }
        } catch (ResponseStatusException error) { throw error;
        } catch (IOException | RuntimeException error) {
            throw fail(415, "PDF 页面无法预览，请下载原文件核对");
        } finally { PARSERS.release(); }
    }

    static void validate(String name, String mime, byte[] bytes) {
        if (mime.startsWith("text/")) {
            String text = utf8(bytes);
            if (text.codePoints().anyMatch(c -> c < 32 && c != '\n' && c != '\r' && c != '\t' && c != '\f'))
                throw fail(415, "文本含二进制控制字符，请使用 UTF-8 文本");
            if (name.toLowerCase(Locale.ROOT).endsWith(".json")) validateJson(text, 415);
            return;
        }
        acquire();
        try {
            if (mime.startsWith("image/")) validateImage(mime, bytes);
            else try (PDDocument document = pdf(bytes)) { checkPdf(document); }
        } catch (ResponseStatusException error) { throw error;
        } catch (IOException | RuntimeException error) {
            throw fail(415, "文件内容损坏、加密或与声明格式不一致");
        } finally { PARSERS.release(); }
    }

    static void validateJson(String text, int status) {
        try {
            var node = JSON.readTree(text.startsWith("\ufeff") ? text.substring(1) : text);
            if (node == null || node.isMissingNode()) throw new IOException();
        } catch (IOException | IllegalArgumentException error) { throw fail(status, "JSON 格式无效或超出解析限制"); }
    }

    static String read(String mime, byte[] bytes, int limit) {
        if (mime.startsWith("text/")) { utf8(bytes); return prefix(bytes, limit); }
        if (!mime.equals("application/pdf")) return "图片仅支持预览和下载，尚未接入视觉识别或 OCR，不能据此推断图片内容。";
        acquire();
        try (PDDocument document = pdf(bytes)) {
            checkPdf(document);
            LimitedWriter output = new LimitedWriter(limit + 1);
            BoundedStripper stripper = new BoundedStripper();
            stripper.setLineSeparator("\n");
            boolean truncated = false;
            try { stripper.writeText(document, output); }
            catch (TextLimit reached) { truncated = true; }
            String text = output.text();
            if (text.isBlank()) return "PDF 共 " + document.getNumberOfPages() + " 页，未提取到文字层；可能为扫描件，尚未接入 OCR，不能据此推断页面内容。";
            byte[] extracted = text.getBytes(StandardCharsets.UTF_8);
            return "[PDF 文字层，共 " + document.getNumberOfPages() + " 页；不包含图片识别，文字顺序与版面可能不同]\n"
                    + prefix(extracted, limit) + (truncated && extracted.length <= limit ? TRUNCATED : "");
        } catch (ResponseStatusException error) { throw error;
        } catch (IOException | RuntimeException error) {
            throw fail(415, "PDF 文字层不可读取，请预览或下载原文件核对");
        } finally { PARSERS.release(); }
    }

    private static void acquire() {
        if (!PARSERS.tryAcquire()) throw fail(429, "文件解析繁忙，请稍后重试；本次操作尚未开始");
    }

    private static void validateImage(String mime, byte[] bytes) throws IOException {
        try (var input = new MemoryCacheImageInputStream(new ByteArrayInputStream(bytes))) {
            var readers = ImageIO.getImageReaders(input);
            if (!readers.hasNext()) throw new IOException();
            ImageReader reader = readers.next();
            try {
                String format = reader.getFormatName().toLowerCase(Locale.ROOT);
                if (!mime.equals("image/" + (format.equals("jpg") ? "jpeg" : format))) throw new IOException();
                boolean[] warning = {false};
                reader.addIIOReadWarningListener((source, message) -> warning[0] = true);
                reader.setInput(input, true, true);
                int width = reader.getWidth(0), height = reader.getHeight(0);
                if (width < 1 || height < 1 || width > 8192 || height > 8192 || (long)width * height > MAX_IMAGE_PIXELS)
                    throw fail(413, "图片尺寸超限：最长边 8192，最多 1600 万像素");
                var image = reader.read(0);
                if (image == null || warning[0]) throw new IOException();
                image.flush();
            } finally { reader.dispose(); }
        }
    }

    private static PDDocument pdf(byte[] bytes) throws IOException {
        if (bytes.length < 12 || !new String(bytes, 0, 5, StandardCharsets.US_ASCII).equals("%PDF-")
                || !new String(bytes, Math.max(0, bytes.length - 1024), Math.min(1024, bytes.length), StandardCharsets.US_ASCII).contains("%%EOF"))
            throw new IOException();
        return Loader.loadPDF(bytes);
    }

    private static void checkPdf(PDDocument document) throws IOException {
        if (document.isEncrypted() || !document.getCurrentAccessPermission().canExtractContent()) throw new IOException();
        if (document.getDocument().getXrefTable().size() > 10000) throw fail(413, "PDF 对象过多，请拆分文件");
        int count = 0;
        for (PDPage page : document.getPages()) {
            if (++count > MAX_PDF_PAGES) throw fail(413, "PDF 最多支持 100 页，请拆分文件");
            var box = page.getMediaBox();
            if (!Float.isFinite(box.getWidth()) || !Float.isFinite(box.getHeight()) || box.getWidth() <= 0 || box.getHeight() <= 0)
                throw new IOException();
        }
        if (count == 0 || count != document.getNumberOfPages()) throw new IOException();
    }

    private static String utf8(byte[] bytes) {
        try { return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString(); }
        catch (CharacterCodingException error) { throw fail(415, "文本编码无效，请转换为 UTF-8 后上传"); }
    }

    static String prefix(byte[] bytes, int limit) {
        int end = Math.min(bytes.length, limit);
        if (end < bytes.length) while (end > 0 && (bytes[end] & 0xc0) == 0x80) end--;
        return new String(bytes, 0, end, StandardCharsets.UTF_8) + (end < bytes.length ? TRUNCATED : "");
    }

    private static final class TextLimit extends IOException {}
    private static final class LimitedWriter extends Writer {
        private final int limit;
        private final StringBuilder buffer = new StringBuilder();
        LimitedWriter(int limit) { this.limit = limit; }
        @Override public void write(char[] chars, int offset, int length) throws IOException {
            int accepted = Math.min(length, limit - buffer.length());
            buffer.append(chars, offset, accepted);
            if (accepted < length) throw new TextLimit();
        }
        String text() {
            if (!buffer.isEmpty() && Character.isHighSurrogate(buffer.charAt(buffer.length() - 1))) buffer.setLength(buffer.length() - 1);
            return buffer.toString();
        }
        @Override public void flush() {}
        @Override public void close() {}
    }

    /** 合作式限制，不能替代独立进程的内存和硬超时隔离。 */
    private static final class BoundedStripper extends PDFTextStripper {
        private final long deadline = System.nanoTime() + 10_000_000_000L;
        private int positions;
        @Override protected void processOperator(Operator operator, List<COSBase> operands) throws IOException {
            if (Thread.currentThread().isInterrupted() || System.nanoTime() > deadline) throw fail(413, "PDF 解析时间超限，请拆分文件");
            super.processOperator(operator, operands);
        }
        @Override protected void processTextPosition(TextPosition position) {
            if (++positions > 200000) throw fail(413, "PDF 文字复杂度超限，请拆分文件");
            super.processTextPosition(position);
        }
    }

    private static ResponseStatusException fail(int status, String message) {
        return new ResponseStatusException(HttpStatus.valueOf(status), message);
    }
}
