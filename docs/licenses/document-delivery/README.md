# 文档交付依赖许可

- Apache POI 6.0.0：Apache License 2.0；使用 Maven 依赖，未复制或修改其实现。上游 [下载与版本说明](https://poi.apache.org/download.html)、[Java 17 兼容性](https://poi.apache.org/help/faq.html)、[legal/LICENSE](https://github.com/apache/poi/blob/trunk/legal/LICENSE)、[legal/NOTICE](https://github.com/apache/poi/blob/trunk/legal/NOTICE)。本目录保存上游许可与 NOTICE；实际构建依赖包中的许可仍须保留。
- Apache PDFBox 3.0.8：沿用父 POM 已管理的版本；许可与 NOTICE 已保存在 `docs/licenses/workspace-file-parsers`，依赖包中的声明保持不变。
- IBM Plex Sans SC Regular：SIL Open Font License 1.1；未修改静态 TTF，完整许可与来源清单和字体一起保存在 `doorhandle-module-detection/src/main/resources/fonts`。下载核对 Git blob 为 `c6165114f070fb7388264fcc6485a3c9d1e0e2ba`，SHA-256 为 `0b8b5c398c3198ec8932f3d3eb5eea0b3e7ff4f6cb5b84fcde180ad890094d5e`。字体可随应用及 PDF 嵌入分发，须保留 OFL 声明；不得把字体文件本身单独售卖。

本轮没有执行 Maven 依赖解析、项目编译或打包，不能据此宣称整个依赖图已验证。POI 6 所需 Commons IO、Compress、Collections、Codec、XMLBeans 与 Log4j 版本在父 POM 显式管理；后续构建应核对这些升级对既有 Agent SDK 和日志桥接的兼容性。
