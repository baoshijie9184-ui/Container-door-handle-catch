package com.ruanzhu.doorhandle.module.app.service.knowledge;

import com.ruanzhu.doorhandle.common.BusinessException;
import com.ruanzhu.doorhandle.module.detection.service.ReportDocumentRenderer;
import org.apache.poi.xwpf.usermodel.XWPFDocument;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.apache.poi.xslf.usermodel.XMLSlideShow;
import org.apache.pdfbox.pdmodel.*;
import org.junit.jupiter.api.Test;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.zip.*;
import static org.assertj.core.api.Assertions.*;

class KnowledgeTextExtractorTest {
    final KnowledgeTextExtractor extractor=new KnowledgeTextExtractor();
    @Test void docxTextKeepsBodyOrderIncludingTables()throws Exception{try(var doc=new XWPFDocument();var out=new ByteArrayOutputStream()){doc.createParagraph().createRun().setText("检查前置条件");doc.createTable(1,1).getRow(0).getCell(0).setText("锈蚀缺陷定义");doc.createParagraph().createRun().setText("复核处理流程");doc.write(out);var text=extractor.extract("标准.docx",out.toByteArray()).content();assertThat(text.indexOf("检查前置条件")).isLessThan(text.indexOf("锈蚀缺陷定义"));assertThat(text.indexOf("锈蚀缺陷定义")).isLessThan(text.indexOf("复核处理流程"));}}
    @Test void spreadsheetUsesCellReferencesAndDoesNotInventUncachedFormulaResults()throws Exception{try(var book=new XSSFWorkbook();var out=new ByteArrayOutputStream()){var sheet=book.createSheet("质检");sheet.createRow(0).createCell(0).setCellValue("门把手");sheet.getRow(0).createCell(2).setCellFormula("1+1");book.write(out);var text=extractor.extract("表格.xlsx",out.toByteArray()).content();assertThat(text).contains("工作表 质检","A1：门把手","C1：[公式，无缓存结果]");}}
    @Test void pptxExtractsActualSlideAndTableText()throws Exception{try(var slides=new XMLSlideShow();var out=new ByteArrayOutputStream()){var slide=slides.createSlide();slide.createTextBox().setText("门把手复核");var table=slide.createTable(1,1);table.getRows().get(0).getCells().get(0).setText("缺陷处理");slides.write(out);assertThat(extractor.extract("培训.pptx",out.toByteArray()).content()).contains("幻灯片 1","门把手复核","缺陷处理");}}
    @Test void pdfChineseTextCanBeIndexedAndEmptyScansAreRejected()throws Exception{var rendered=new ReportDocumentRenderer().render("# 门把手检验规范\n锈蚀缺陷必须复核\n","pdf");assertThat(extractor.extract("规范.pdf",rendered.bytes()).content()).contains("第 1 页","门把手检验规范","锈蚀缺陷必须复核");try(var scan=new PDDocument();var out=new ByteArrayOutputStream()){scan.addPage(new PDPage());scan.save(out);assertThatThrownBy(()->extractor.extract("扫描件.pdf",out.toByteArray())).isInstanceOf(BusinessException.class).hasMessageContaining("OCR");}}
    @Test void binarySpoofMalformedUtf8AndOversizedTextNeverProduceReadyIndex(){assertThatThrownBy(()->extractor.extract("伪装.docx","not a zip".getBytes(StandardCharsets.UTF_8))).isInstanceOf(BusinessException.class);assertThatThrownBy(()->extractor.extract("乱码.txt",new byte[]{(byte)0xc3,(byte)0x28})).isInstanceOf(BusinessException.class);assertThatThrownBy(()->extractor.extract("过长.txt","x".repeat(200001).getBytes(StandardCharsets.UTF_8))).hasMessageContaining("20 万");}
    @Test void macroPayloadIsRejectedBeforeOfficeParsing()throws Exception{try(var out=new ByteArrayOutputStream()){try(var zip=new ZipOutputStream(out)){zip.putNextEntry(new ZipEntry("word/vbaProject.bin"));zip.write(new byte[]{1,2,3});zip.closeEntry();}assertThatThrownBy(()->extractor.extract("含宏.docx",out.toByteArray())).isInstanceOf(BusinessException.class).hasMessageContaining("宏");}}
}
