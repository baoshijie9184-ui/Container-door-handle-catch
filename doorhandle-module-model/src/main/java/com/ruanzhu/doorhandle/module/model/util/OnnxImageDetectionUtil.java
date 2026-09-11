package com.ruanzhu.doorhandle.module.model.util;

import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OnnxValue;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtException;
import ai.onnxruntime.OrtSession;
import lombok.extern.slf4j.Slf4j;
import org.opencv.core.Core;
import org.opencv.core.CvType;
import org.opencv.core.Mat;
import org.opencv.core.Point;
import org.opencv.core.Scalar;
import org.opencv.core.Size;
import org.opencv.imgcodecs.Imgcodecs;
import org.opencv.imgproc.Imgproc;

import java.nio.FloatBuffer;
import java.util.AbstractMap;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

@Slf4j
public class OnnxImageDetectionUtil {

    private static final String[] CATEGORY_ORDER = {
            "Normal", "Bent", "Deformed", "Rusty", "Missing", "Compromised"
    };
    private static final Map<String, Scalar> CLASS_COLORS = new LinkedHashMap<>();

    static {
        nu.pattern.OpenCV.loadLocally();
        CLASS_COLORS.put("Normal", new Scalar(0, 255, 0));
        CLASS_COLORS.put("Bent", new Scalar(0, 165, 255));
        CLASS_COLORS.put("Deformed", new Scalar(0, 215, 255));
        CLASS_COLORS.put("Rusty", new Scalar(42, 42, 165));
        CLASS_COLORS.put("Missing", new Scalar(0, 0, 255));
        CLASS_COLORS.put("Compromised", new Scalar(128, 0, 128));
        CLASS_COLORS.put("UNKNOWN", new Scalar(255, 255, 255));
    }

    private OnnxImageDetectionUtil() {
    }

    public static OrtSession loadModel(String modelPath) throws OrtException {
        OrtEnvironment env = OrtEnvironment.getEnvironment();
        return env.createSession(modelPath, new OrtSession.SessionOptions());
    }

    public static Mat preProcessImage(String imagePath) {
        Mat image = Imgcodecs.imread(imagePath);
        if (image.empty()) {
            throw new IllegalArgumentException("无法读取图像: " + imagePath);
        }

        Mat resizedImage = new Mat();
        Imgproc.resize(image, resizedImage, new Size(640, 640));
        image.release();

        Mat rgbImage = new Mat();
        Imgproc.cvtColor(resizedImage, rgbImage, Imgproc.COLOR_BGR2RGB);
        resizedImage.release();

        Mat normalizedImage = new Mat();
        rgbImage.convertTo(normalizedImage, CvType.CV_32FC3, 1.0 / 255.0);
        rgbImage.release();
        return normalizedImage;
    }

    public static OnnxTensor imageToTensor(OrtEnvironment env, Mat image) throws OrtException {
        Mat processedImage = image;
        if (image.type() != CvType.CV_32FC3) {
            processedImage = new Mat();
            image.convertTo(processedImage, CvType.CV_32FC3);
        }

        int height = processedImage.rows();
        int width = processedImage.cols();
        int channels = processedImage.channels();
        FloatBuffer floatBuffer = FloatBuffer.allocate(height * width * channels);
        float[] pixelData = new float[channels];

        for (int h = 0; h < height; h++) {
            for (int w = 0; w < width; w++) {
                processedImage.get(h, w, pixelData);
                for (int c = 0; c < channels; c++) {
                    floatBuffer.put(pixelData[c]);
                }
            }
        }

        if (processedImage != image) {
            processedImage.release();
        }

        floatBuffer.rewind();
        long[] shape = new long[]{1, channels, height, width};
        return OnnxTensor.createTensor(env, floatBuffer, shape);
    }

    public static Map<String, Float> runInference(OrtSession session, OnnxTensor inputTensor) throws OrtException {
        String inputName = session.getInputNames().iterator().next();
        try (OrtSession.Result results = session.run(Collections.singletonMap(inputName, inputTensor))) {
            String outputName = session.getOutputNames().iterator().next();
            Optional<OnnxValue> outputOptional = results.get(outputName);
            if (outputOptional.isPresent() && outputOptional.get() instanceof OnnxTensor outputTensor) {
                long[] shape = outputTensor.getInfo().getShape();
                if (shape.length == 2 && shape[0] == 1) {
                    float[] scores = outputTensor.getFloatBuffer().array();
                    float[] probabilities = softmax(scores);
                    return mapProbabilities(probabilities);
                }
            }
            return defaultConfidenceMap();
        } catch (Exception e) {
            log.warn("模型推理输出解析失败，使用默认概率", e);
            return defaultConfidenceMap();
        }
    }

    public static Map.Entry<String, Float> getTopCategory(Map<String, Float> categoryConfidenceMap) {
        if (categoryConfidenceMap == null || categoryConfidenceMap.isEmpty()) {
            return new AbstractMap.SimpleEntry<>("UNKNOWN", 0.0f);
        }

        return categoryConfidenceMap.entrySet()
                .stream()
                .max(Map.Entry.comparingByValue())
                .orElse(new AbstractMap.SimpleEntry<>("UNKNOWN", 0.0f));
    }

    public static String drawDetectionResult(String imagePath, String category, float confidence, String outputPath) {
        try {
            Mat image = Imgcodecs.imread(imagePath);
            if (image.empty()) {
                return imagePath;
            }

            String displayCategory = switch (category) {
                case "Normal", "Bent", "Deformed", "Rusty", "Missing", "Compromised" -> category;
                default -> "UNKNOWN";
            };
            float normalizedConfidence = Math.max(0.0f, Math.min(1.0f, confidence));
            String confidenceStr = String.format("%.2f%%", normalizedConfidence * 100);
            Scalar color = CLASS_COLORS.getOrDefault(displayCategory, CLASS_COLORS.get("UNKNOWN"));

            int fontFace = Imgproc.FONT_HERSHEY_SIMPLEX;
            double fontScale = 1.2;
            int thickness = 2;
            String label = displayCategory + " " + confidenceStr;

            Size labelSize = Imgproc.getTextSize(label, fontFace, fontScale, thickness, null);
            int padding = 12;
            Point topLeft = new Point(20, 20);
            Point bottomRight = new Point(20 + labelSize.width + padding * 2, 20 + labelSize.height + padding * 2);

            Mat overlay = image.clone();
            Imgproc.rectangle(overlay, topLeft, bottomRight, color, -1);
            Core.addWeighted(overlay, 0.75, image, 0.25, 0, image);
            overlay.release();

            Imgproc.putText(
                    image,
                    label,
                    new Point(20 + padding, 20 + labelSize.height + 4),
                    fontFace,
                    fontScale,
                    new Scalar(255, 255, 255),
                    thickness
            );

            Imgcodecs.imwrite(outputPath, image);
            image.release();
            return outputPath;
        } catch (Exception e) {
            log.error("绘制检测结果失败", e);
            return imagePath;
        }
    }

    static Map<String, Float> mapProbabilitiesForTest(float[] probabilities) {
        return mapProbabilities(probabilities);
    }

    private static Map<String, Float> mapProbabilities(float[] probabilities) {
        Map<String, Float> categoryConfidenceMap = new LinkedHashMap<>();
        if (probabilities.length >= CATEGORY_ORDER.length) {
            for (int i = 0; i < CATEGORY_ORDER.length; i++) {
                categoryConfidenceMap.put(CATEGORY_ORDER[i], probabilities[i]);
            }
            return categoryConfidenceMap;
        }
        return defaultConfidenceMap();
    }

    private static Map<String, Float> defaultConfidenceMap() {
        Map<String, Float> defaultConfidenceMap = new LinkedHashMap<>();
        defaultConfidenceMap.put("Normal", 0.2f);
        defaultConfidenceMap.put("Bent", 0.16f);
        defaultConfidenceMap.put("Deformed", 0.16f);
        defaultConfidenceMap.put("Rusty", 0.16f);
        defaultConfidenceMap.put("Missing", 0.16f);
        defaultConfidenceMap.put("Compromised", 0.16f);
        return defaultConfidenceMap;
    }

    private static float[] softmax(float[] scores) {
        float[] probabilities = new float[scores.length];
        float maxScore = Float.NEGATIVE_INFINITY;
        for (float score : scores) {
            if (score > maxScore) {
                maxScore = score;
            }
        }

        float sum = 0.0f;
        for (int i = 0; i < scores.length; i++) {
            probabilities[i] = (float) Math.exp(scores[i] - maxScore);
            sum += probabilities[i];
        }

        if (sum <= 0) {
            Arrays.fill(probabilities, 1.0f / Math.max(1, probabilities.length));
            return probabilities;
        }

        for (int i = 0; i < probabilities.length; i++) {
            probabilities[i] /= sum;
        }
        return probabilities;
    }
}
