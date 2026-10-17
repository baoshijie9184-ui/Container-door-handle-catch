package com.ruanzhu.doorhandle.module.app.service.impl;

import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.apache.pdfbox.pdmodel.encryption.AccessPermission;
import org.apache.pdfbox.pdmodel.encryption.StandardProtectionPolicy;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.web.server.ResponseStatusException;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Base64;

import static org.assertj.core.api.Assertions.*;

class WorkspaceFileContentTest {
    @ParameterizedTest @ValueSource(strings={"png","jpeg"})
    void realImagesDecodeAndTruncatedImagesDoNotPass(String format) throws Exception {
        var out = new ByteArrayOutputStream();
        ImageIO.write(new BufferedImage(20,10,BufferedImage.TYPE_INT_RGB),format,out);
        byte[] data = out.toByteArray();
        assertThatCode(() -> WorkspaceFileContent.validate("image."+format,"image/"+format,data)).doesNotThrowAnyException();
        assertThatThrownBy(() -> WorkspaceFileContent.validate("image."+format,"image/"+format,Arrays.copyOf(data,data.length/2))).isInstanceOf(ResponseStatusException.class).hasMessageContaining("415");
        assertThatThrownBy(() -> WorkspaceFileContent.validate("image.webp","image/webp",data)).hasMessageContaining("415");
    }

    @Test void webpUsesARealDecoderInsteadOfTrustingRiffHeaders() {
        byte[] data = Base64.getDecoder().decode("UklGRh4AAABXRUJQVlA4TBEAAAAvAkAAAAdQqGaUsf+BiOh/AAA=");
        assertThatCode(() -> WorkspaceFileContent.validate("image.webp","image/webp",data)).doesNotThrowAnyException();
        assertThatThrownBy(() -> WorkspaceFileContent.validate("broken.webp","image/webp","RIFF0000WEBPgarbage".getBytes(StandardCharsets.US_ASCII))).hasMessageContaining("415");
    }

    @Test void oversizedDimensionsAreRejectedBeforeAllocatingTheDecodedImage() throws Exception {
        var out = new ByteArrayOutputStream();
        ImageIO.write(new BufferedImage(8193,1,BufferedImage.TYPE_INT_RGB),"png",out);
        assertThatThrownBy(() -> WorkspaceFileContent.validate("wide.png","image/png",out.toByteArray())).hasMessageContaining("413");
    }

    @Test void textEncodingJsonDepthAndTrailingDataAreValidated() {
        assertThatThrownBy(() -> WorkspaceFileContent.validate("notes.txt","text/plain",new byte[]{(byte)0xe4,(byte)0xbd})).hasMessageContaining("UTF-8");
        assertThatThrownBy(() -> WorkspaceFileContent.validate("notes.txt","text/plain",new byte[]{65,0,66})).hasMessageContaining("控制字符");
        for (String invalid : new String[]{"{bad}","{} []"," ","[".repeat(101)+"0"+"]".repeat(101)})
            assertThatThrownBy(() -> WorkspaceFileContent.validate("data.JSON","text/plain",invalid.getBytes(StandardCharsets.UTF_8))).hasMessageContaining("415");
        assertThatCode(() -> WorkspaceFileContent.validate("data.json","text/plain","\ufeff{\"编号\":1}".getBytes(StandardCharsets.UTF_8))).doesNotThrowAnyException();
        assertThatCode(() -> WorkspaceFileContent.validate("source.svg","text/plain","<svg onload='alert(1)'/>".getBytes(StandardCharsets.UTF_8))).doesNotThrowAnyException();
    }

    @Test void utf8ClippingNeverSplitsChineseOrSupplementaryCharacters() {
        byte[] text="A中𠀀B".getBytes(StandardCharsets.UTF_8);
        assertThat(WorkspaceFileContent.read("text/plain",text,3)).isEqualTo("A"+WorkspaceFileContent.TRUNCATED);
        assertThat(WorkspaceFileContent.read("text/plain",text,7)).isEqualTo("A中"+WorkspaceFileContent.TRUNCATED);
        assertThat(WorkspaceFileContent.read("text/plain",text,8)).isEqualTo("A中𠀀"+WorkspaceFileContent.TRUNCATED);
        assertThat(WorkspaceFileContent.read("text/plain",text,9)).isEqualTo("A中𠀀B");
    }

    @Test void pdfMagicAloneAndTruncatedOrEncryptedDocumentsAreRejected() throws Exception {
        assertThatThrownBy(() -> WorkspaceFileContent.validate("broken.pdf","application/pdf","%PDF-1.7\nnot a document\n%%EOF".getBytes(StandardCharsets.US_ASCII))).hasMessageContaining("415");
        byte[] valid=pdf("EVIDENCE-20261018");
        assertThatCode(() -> WorkspaceFileContent.validate("report.pdf","application/pdf",valid)).doesNotThrowAnyException();
        assertThatThrownBy(() -> WorkspaceFileContent.validate("broken.pdf","application/pdf",Arrays.copyOf(valid,valid.length/2))).hasMessageContaining("415");
        try(var document=new PDDocument();var out=new ByteArrayOutputStream()) {
            document.addPage(new PDPage());
            document.protect(new StandardProtectionPolicy("owner-secret","",new AccessPermission()));
            document.save(out);
            assertThatThrownBy(() -> WorkspaceFileContent.validate("locked.pdf","application/pdf",out.toByteArray())).hasMessageContaining("415");
        }
    }

    @Test void pdfTextLayerIsReadWithLimitsButAnEmptyPageDoesNotPretendToBeOcr() throws Exception {
        byte[] data=pdf("EVIDENCE-20261018");
        assertThat(WorkspaceFileContent.read("application/pdf",data,64000)).contains("PDF 文字层","EVIDENCE-20261018","不包含图片识别");
        assertThat(WorkspaceFileContent.read("application/pdf",data,4)).contains("EVID",WorkspaceFileContent.TRUNCATED).doesNotContain("EVIDENCE");
        try(var document=new PDDocument();var out=new ByteArrayOutputStream()) {
            document.addPage(new PDPage());document.save(out);
            assertThat(WorkspaceFileContent.read("application/pdf",out.toByteArray(),64000)).contains("未提取到文字层","尚未接入 OCR");
        }
        assertThat(WorkspaceFileContent.read("image/png",new byte[0],64000)).contains("尚未接入视觉识别或 OCR");
    }

    @Test void pdfPageCountIsEnforced() throws Exception {
        try(var document=new PDDocument();var out=new ByteArrayOutputStream()) {
            for(int i=0;i<101;i++)document.addPage(new PDPage());document.save(out);
            assertThatThrownBy(() -> WorkspaceFileContent.validate("large.pdf","application/pdf",out.toByteArray())).hasMessageContaining("413");
        }
    }

    @Test void pdfPreviewIsAnActualRasterPageWithNoEmbeddedActions() throws Exception {
        byte[] documentBytes;
        try(var document=new PDDocument();var output=new ByteArrayOutputStream()){
            for(var color:new java.awt.Color[]{java.awt.Color.BLUE,java.awt.Color.GREEN}){
                var page=new PDPage(new org.apache.pdfbox.pdmodel.common.PDRectangle(300,200));document.addPage(page);
                try(var content=new org.apache.pdfbox.pdmodel.PDPageContentStream(document,page)){content.setNonStrokingColor(color);content.addRect(0,0,300,200);content.fill();}
            }
            document.getDocumentCatalog().setOpenAction(new org.apache.pdfbox.pdmodel.interactive.action.PDActionJavaScript("app.alert('NEVER_EXECUTE')"));
            document.save(output);documentBytes=output.toByteArray();
        }
        var first=WorkspaceFileContent.previewPdf(documentBytes,1);var second=WorkspaceFileContent.previewPdf(documentBytes,2);
        var image=ImageIO.read(new java.io.ByteArrayInputStream(first.png()));
        assertThat(first.page()).isEqualTo(1);assertThat(first.pages()).isEqualTo(2);assertThat(second.page()).isEqualTo(2);
        assertThat(image.getWidth()).isLessThanOrEqualTo(1800);assertThat(image.getHeight()).isLessThanOrEqualTo(1800);
        assertThat(image.getRGB(10,10)).isEqualTo(java.awt.Color.BLUE.getRGB());
        assertThat(ImageIO.read(new java.io.ByteArrayInputStream(second.png())).getRGB(10,10)).isEqualTo(java.awt.Color.GREEN.getRGB());
        java.nio.file.Files.write(java.nio.file.Path.of("target/pdf-preview-acceptance.pdf"),documentBytes);
        java.nio.file.Files.write(java.nio.file.Path.of("target/pdf-preview-page1.png"),first.png());
        java.nio.file.Files.write(java.nio.file.Path.of("target/pdf-preview-page2.png"),second.png());
        assertThatThrownBy(()->WorkspaceFileContent.previewPdf(documentBytes,3)).hasMessageContaining("400");
        assertThatThrownBy(()->WorkspaceFileContent.previewPdf(pdf("text"),0)).hasMessageContaining("400");
    }

    /** 直接构造带交叉引用表的简单 PDF，避免依赖被测解析器生成同一份文字层。 */
    static byte[] pdf(String text) {
        String stream="BT /F1 12 Tf 40 700 Td ("+text+") Tj ET";
        String[] objects={"<< /Type /Catalog /Pages 2 0 R >>","<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>","<< /Length "+stream.length()+" >>\nstream\n"+stream+"\nendstream"};
        StringBuilder pdf=new StringBuilder("%PDF-1.4\n");int[] offsets=new int[objects.length];
        for(int i=0;i<objects.length;i++){offsets[i]=pdf.length();pdf.append(i+1).append(" 0 obj\n").append(objects[i]).append("\nendobj\n");}
        int xref=pdf.length();pdf.append("xref\n0 6\n0000000000 65535 f \n");
        for(int offset:offsets)pdf.append(String.format(java.util.Locale.ROOT,"%010d 00000 n \n",offset));
        return pdf.append("trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n").append(xref).append("\n%%EOF\n").toString().getBytes(StandardCharsets.US_ASCII);
    }
}
