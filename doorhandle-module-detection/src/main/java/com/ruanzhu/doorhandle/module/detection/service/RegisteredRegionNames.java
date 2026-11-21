package com.ruanzhu.doorhandle.module.detection.service;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.regex.Pattern;

/** Resolves unambiguous administrative place names to the configured collection cities. */
public final class RegisteredRegionNames {
    public static final List<String> COLLECTION_CITIES = List.of(
            "大连市", "天津市", "青岛市", "重庆市", "武汉市", "南京市", "上海市", "宁波市", "广州市", "钦州市");

    private RegisteredRegionNames() {}
    // National Place Names Database, 2025 year end. CC0 transcription, unmodified:
    // https://github.com/yescallop/areacodes/blob/2da87e7648f0da7e10dea39e8a613107ed3fe273/data/2025.txt
    private static final String RESOURCE = "/geography/cn-divisions-2025.txt";
    private static final Pattern SEPARATORS = Pattern.compile("[\\s\\p{Zs}_/／>·-]+");
    private static final Map<String,String> PROVINCE_SHORT_NAMES = Map.of(
            "内蒙古自治区","内蒙古", "广西壮族自治区","广西", "西藏自治区","西藏",
            "宁夏回族自治区","宁夏", "新疆维吾尔自治区","新疆",
            "香港特别行政区","香港", "澳门特别行政区","澳门");
    private static final Map<String,String> LABELS = load();

    static String lookup(String raw) {
        if (raw == null || raw.isBlank()) return null;
        String label = LABELS.get(SEPARATORS.matcher(raw.strip()).replaceAll(" "));
        return label == null || label.isEmpty() ? null : label;
    }

    private static Map<String,String> load() {
        Map<String,String> names = new HashMap<>();
        try (var reader = new BufferedReader(new InputStreamReader(
                Objects.requireNonNull(RegisteredRegionNames.class.getResourceAsStream(RESOURCE)), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                String name = line.substring(7);
                names.put(line.substring(0,6), name);
            }
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }

        Map<String,String> labels = new HashMap<>();
        names.forEach((code, name) -> {
            String province = names.get(code.substring(0,2) + "0000");
            String city = names.get(code.substring(0,4) + "00");
            boolean topLevel = code.endsWith("0000");
            boolean county = !code.endsWith("00");
            List<String> local = county ? List.of(name) : aliases(name);
            String collectionCity = COLLECTION_CITIES.contains(province) ? province
                    : city != null && COLLECTION_CITIES.contains(city) ? city : "";
            for (String alias : local) add(labels, alias, collectionCity);
            if (topLevel) return;

            for (String p : aliases(province)) {
                addQualified(labels, p, local, collectionCity);
            }
            if (county && city != null) {
                for (String c : aliases(city)) {
                    addQualified(labels, c, local, collectionCity);
                    for (String p : aliases(province)) {
                        addQualified(labels, p + c, local, collectionCity);
                        addQualified(labels, p + " " + c, local, collectionCity);
                    }
                }
            }
        });
        return Map.copyOf(labels);
    }

    private static List<String> aliases(String name) {
        String shortName = PROVINCE_SHORT_NAMES.get(name);
        if (shortName == null && (name.endsWith("市") || name.endsWith("省"))) {
            shortName = name.substring(0, name.length()-1);
        }
        return shortName == null ? List.of(name) : List.of(name, shortName);
    }

    private static void addQualified(Map<String,String> labels, String parent, List<String> local, String label) {
        for (String name : local) {
            add(labels, parent + name, label);
            add(labels, parent + " " + name, label);
        }
    }

    private static void add(Map<String,String> labels, String alias, String label) {
        labels.merge(alias, label, (first, second) -> first.equals(second) ? first : "");
    }
}
