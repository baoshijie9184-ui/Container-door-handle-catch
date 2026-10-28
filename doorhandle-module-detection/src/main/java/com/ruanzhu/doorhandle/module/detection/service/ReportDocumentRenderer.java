package com.ruanzhu.doorhandle.module.detection.service;

import com.ruanzhu.doorhandle.common.BusinessException;
import org.apache.poi.xwpf.usermodel.XWPFDocument;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.apache.pdfbox.pdmodel.*;
import org.apache.pdfbox.pdmodel.common.PDRectangle;
import org.apache.pdfbox.pdmodel.font.PDType0Font;
import org.springframework.stereotype.Component;
import java.io.*;
import java.util.*;
import java.util.concurrent.Semaphore;

/** Pure rendering of already-authorized, frozen text. No model, network, or business writes. */
@Component
public class ReportDocumentRenderer {
    public record File(byte[] bytes,String mediaType,String extension) { }
    private static final Semaphore RENDERS=new Semaphore(2);
    private static final Map<String,String> TYPES=Map.of("docx","application/vnd.openxmlformats-officedocument.wordprocessingml.document","xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet","pdf","application/pdf");
    public File render(String text,String format) {
        if(!TYPES.containsKey(format))throw new BusinessException(400,"支持 DOCX、PDF 和 XLSX");
        if(text.length()>100_000)throw new BusinessException(413,"报告内容过长，请拆分导出");
        if(!RENDERS.tryAcquire())throw new BusinessException(429,"报告生成繁忙，请稍后重试");
        try(var output=new ByteArrayOutputStream()) {
            switch(format) {
                case "docx" -> { try(var document=new XWPFDocument()){for(String line:lines(text)){var paragraph=document.createParagraph();boolean heading=line.startsWith("#");var run=paragraph.createRun();run.setFontFamily("IBM Plex Sans SC");run.setFontSize(heading?16:11);run.setBold(heading);if(heading)run.setColor("1D4ED8");run.setText(line.replaceFirst("^#+\\s*",""));paragraph.setSpacingAfter(100);}document.write(output);} }
                case "xlsx" -> { try(var workbook=new XSSFWorkbook()){var sheet=workbook.createSheet("检测报告");int row=0;for(String line:lines(text)){var cells=sheet.createRow(row++);int separator=line.indexOf('：');if(separator>0&&separator<60){cells.createCell(0).setCellValue(line.substring(0,separator).replaceFirst("^- ",""));cells.createCell(1).setCellValue(line.substring(separator+1));}else cells.createCell(0).setCellValue(line.replaceFirst("^#+\\s*",""));}sheet.setColumnWidth(0,32*256);sheet.setColumnWidth(1,90*256);var style=workbook.createCellStyle();style.setWrapText(true);for(var item:sheet)for(var cell:item)cell.setCellStyle(style);sheet.createFreezePane(0,1);workbook.write(output);} }
                case "pdf" -> pdf(text,output);
                default -> throw new IllegalStateException();
            }
            return new File(output.toByteArray(),TYPES.get(format),format);
        } catch(BusinessException error){throw error;
        } catch(IOException|IllegalArgumentException error){throw new BusinessException(422,"报告文件未能生成，请核对内容后重试");
        } finally{RENDERS.release();}
    }
    private static String[] lines(String text){return text.replace("\r","").replace("\t","    ").replaceAll("[\\p{Cntrl}&&[^\\n]]","").split("\n",-1);}
    private static void pdf(String text,OutputStream output)throws IOException {
        try(var document=new PDDocument();var fontStream=ReportDocumentRenderer.class.getResourceAsStream("/fonts/IBMPlexSansSC-Regular.ttf")) {
            if(fontStream==null)throw new BusinessException(503,"中文报告字体暂不可用");
            var font=PDType0Font.load(document,fontStream,true);var wrapped=new ArrayList<String>();
            for(String raw:lines(text)) {
                String line=raw.replaceFirst("^#+\\s*","");var part=new StringBuilder();
                for(int offset=0;offset<line.length();){int code=line.codePointAt(offset);offset+=Character.charCount(code);String letter=new String(Character.toChars(code));
                    try{font.encode(letter);}catch(IllegalArgumentException error){throw new BusinessException(422,"报告包含当前字体不支持的字符，请调整后导出");}
                    if(font.getStringWidth(part+letter)/1000*11>PDRectangle.A4.getWidth()-96&&part.length()>0){wrapped.add(part.toString());part.setLength(0);}part.append(letter);
                }
                wrapped.add(part.toString());
            }
            if(wrapped.size()>5000)throw new BusinessException(413,"报告分页超出上限");
            int position=0,pageNo=0;
            while(position<wrapped.size()) {
                var page=new PDPage(PDRectangle.A4);document.addPage(page);pageNo++;
                try(var stream=new PDPageContentStream(document,page)) {
                    stream.beginText();stream.setFont(font,11);stream.setLeading(17);stream.newLineAtOffset(48,page.getMediaBox().getHeight()-52);
                    for(int row=0;row<42&&position<wrapped.size();row++){stream.showText(wrapped.get(position++));stream.newLine();}
                    stream.endText();stream.beginText();stream.setFont(font,9);stream.newLineAtOffset(48,34);stream.showText("第 "+pageNo+" 页");stream.endText();
                }
            }
            document.save(output);
        }
    }
}
