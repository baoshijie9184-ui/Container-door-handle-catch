package com.ruanzhu.doorhandle.module.app.config;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.config.YamlPropertiesFactoryBean;
import org.springframework.core.io.FileSystemResource;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.Node;
import org.w3c.dom.NodeList;

import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilderFactory;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Properties;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import java.util.stream.Stream;

import static java.nio.charset.StandardCharsets.UTF_8;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.SoftAssertions.assertSoftly;

class ConfigurationTopologyContractTest {

    private static final Path PROJECT_ROOT = locateProjectRoot();
    private static final Path MAIN_JAVA = PROJECT_ROOT;
    private static final Path APPLICATION_PACKAGE = PROJECT_ROOT.resolve(
            "doorhandle-server/src/main/java/com/ruanzhu/doorhandle/server");
    private static final Path MAIN_RESOURCES = PROJECT_ROOT.resolve("doorhandle-server/src/main/resources");
    private static final Path APPLICATION_YAML = MAIN_RESOURCES.resolve("application.yml");

    @Test
    void usesApplicationYamlAsTheOnlyApplicationConfigurationFile() throws IOException {
        List<String> applicationConfigs;
        try (Stream<Path> resources = Files.walk(MAIN_RESOURCES)) {
            applicationConfigs = resources
                    .filter(Files::isRegularFile)
                    .filter(ConfigurationTopologyContractTest::isApplicationConfig)
                    .map(MAIN_RESOURCES::relativize)
                    .map(ConfigurationTopologyContractTest::normalizePath)
                    .sorted()
                    .toList();
        }

        assertThat(applicationConfigs).containsExactly("application.yml");
    }

    @Test
    void usesOnlyTheSpringBoot3MybatisPlusStarter() throws Exception {
        Set<String> dependencies = new LinkedHashSet<>();
        try (Stream<Path> poms = Files.walk(PROJECT_ROOT, 2)) {
            for (Path pom : poms.filter(path -> path.getFileName().toString().equals("pom.xml")).toList()) {
                dependencies.addAll(projectDependencies(pom));
            }
        }

        assertSoftly(softly -> {
            softly.assertThat(dependencies).contains("com.baomidou:mybatis-plus-spring-boot3-starter");
            softly.assertThat(dependencies).doesNotContain(
                    "org.mybatis.spring.boot:mybatis-spring-boot-starter",
                    "com.baomidou:mybatis-plus-boot-starter"
            );
        });
    }

    @Test
    void doesNotCarryMybatisPlusStartupWorkarounds() throws IOException {
        Properties applicationProperties = loadApplicationProperties();

        List<String> forbiddenPropertiesPresent = forbiddenPropertiesPresent(
                applicationProperties,
                "spring.main.allow-bean-definition-overriding",
                "mybatis-plus.global-config.enable-sql-runner"
        );

        List<JavaWorkaroundPattern> workaroundPatterns = List.of(
                new JavaWorkaroundPattern(
                        "MybatisPlusAutoConfiguration import",
                        Pattern.compile(
                                "(?m)^\\s*import\\s+com\\.baomidou\\.mybatisplus\\.autoconfigure"
                                        + "\\.MybatisPlusAutoConfiguration\\s*;"
                        )
                ),
                new JavaWorkaroundPattern(
                        "MybatisPlusAutoConfiguration excluded from @SpringBootApplication",
                        Pattern.compile(
                                "(?ms)^\\s*@(?:org\\.springframework\\.boot\\.autoconfigure\\.)?"
                                        + "SpringBootApplication\\s*\\([^)]*\\bexclude\\s*=\\s*"
                                        + "(?:\\{[^}]*\\bMybatisPlusAutoConfiguration\\s*\\.\\s*class[^}]*}"
                                        + "|\\bMybatisPlusAutoConfiguration\\s*\\.\\s*class)[^)]*\\)"
                        )
                ),
                new JavaWorkaroundPattern(
                        "ddlApplicationRunner method declaration",
                        Pattern.compile(
                                "(?m)^\\s*(?:(?:public|protected|private|static|final|synchronized|abstract|"
                                        + "native|default)\\s+)*[\\w.$<>?,\\[\\]]+\\s+"
                                        + "ddlApplicationRunner\\s*\\("
                        )
                ),
                new JavaWorkaroundPattern(
                        "enable-sql-runner system property assignment",
                        Pattern.compile(
                                "(?m)^\\s*System\\s*\\.\\s*setProperty\\s*\\(\\s*"
                                        + "\"mybatis-plus\\.global-config\\.enable-sql-runner\"\\s*,"
                        )
                )
        );
        Map<Path, List<String>> workaroundsBySource = new LinkedHashMap<>();
        List<Path> javaSources;
        try (Stream<Path> sourceFiles = Files.walk(MAIN_JAVA)) {
            javaSources = sourceFiles
                    .filter(Files::isRegularFile)
                    .filter(path -> path.getFileName().toString().endsWith(".java"))
                    .filter(path -> normalizePath(PROJECT_ROOT.relativize(path)).contains("/src/main/java/"))
                    .toList();
        }
        for (Path javaSource : javaSources) {
            String sourceWithoutComments = removeJavaComments(Files.readString(javaSource, UTF_8));
            List<String> matchingTokens = workaroundPatterns.stream()
                    .filter(workaround -> workaround.pattern().matcher(sourceWithoutComments).find())
                    .map(JavaWorkaroundPattern::description)
                    .toList();
            if (!matchingTokens.isEmpty()) {
                workaroundsBySource.put(PROJECT_ROOT.relativize(javaSource), matchingTokens);
            }
        }

        assertSoftly(softly -> {
            softly.assertThat(forbiddenPropertiesPresent)
                    .as("forbidden expanded application.yml property names")
                    .isEmpty();
            softly.assertThat(workaroundsBySource)
                    .as("MyBatis-Plus startup workaround tokens by Java source")
                    .isEmpty();
        });
    }

    @Test
    void removesRedundantConfigurationClasses() {
        Path configPackage = APPLICATION_PACKAGE.resolve("config");
        List<String> redundantConfigurationClasses = List.of(
                "CustomMybatisConfig.java",
                "MybatisPlusRunnerConfig.java",
                "DatabaseConfig.java",
                "DatabaseInitConfig.java",
                "WebConfig.java"
        );

        assertThat(redundantConfigurationClasses)
                .map(configPackage::resolve)
                .allSatisfy(path -> assertThat(path).doesNotExist());
    }

    @Test
    void reliesOnConsoleLoggingWithoutFileLoggingConfiguration() {
        Properties applicationProperties = loadApplicationProperties();

        List<String> forbiddenPropertiesPresent = forbiddenPropertiesPresent(
                applicationProperties,
                "logging.file.name",
                "logging.file.path",
                "logging.config"
        );
        assertSoftly(softly -> {
            List.of(
                    "logback-spring.xml",
                    "logback.xml",
                    "log4j2-spring.xml",
                    "log4j2.xml"
            ).forEach(fileName -> softly.assertThat(MAIN_RESOURCES.resolve(fileName)).doesNotExist());
            softly.assertThat(forbiddenPropertiesPresent)
                    .as("forbidden expanded application.yml property names")
                    .isEmpty();
        });
    }

    private static Properties loadApplicationProperties() {
        YamlPropertiesFactoryBean yaml = new YamlPropertiesFactoryBean();
        yaml.setResources(new FileSystemResource(APPLICATION_YAML));
        return Objects.requireNonNull(
                yaml.getObject(),
                () -> "Unable to load YAML properties from " + APPLICATION_YAML
        );
    }

    private static boolean isApplicationConfig(Path path) {
        String fileName = path.getFileName().toString();
        return fileName.startsWith("application")
                && (fileName.endsWith(".yml")
                || fileName.endsWith(".yaml")
                || fileName.endsWith(".properties"));
    }

    private static String normalizePath(Path path) {
        return path.toString().replace('\\', '/');
    }

    private static String removeJavaComments(String source) {
        return source
                .replaceAll("(?s)/\\*.*?\\*/", "")
                .replaceAll("(?m)//.*$", "");
    }

    private static Set<String> propertyNames(Properties properties) {
        return properties.keySet().stream()
                .map(Object::toString)
                .collect(Collectors.toUnmodifiableSet());
    }

    private static List<String> forbiddenPropertiesPresent(Properties properties, String... forbiddenNames) {
        Set<String> propertyNames = propertyNames(properties);
        return Stream.of(forbiddenNames)
                .filter(propertyNames::contains)
                .toList();
    }

    private static Set<String> projectDependencies(Path pom) throws Exception {
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setNamespaceAware(true);
        factory.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
        factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_DTD, "");
        factory.setAttribute(XMLConstants.ACCESS_EXTERNAL_SCHEMA, "");
        factory.setExpandEntityReferences(false);

        Document document;
        try (InputStream input = Files.newInputStream(pom)) {
            document = factory.newDocumentBuilder().parse(input);
        }

        Set<String> dependencies = new LinkedHashSet<>();
        Element project = document.getDocumentElement();
        collectDependencies(project, dependencies);
        for (Element profiles : directChildren(project, "profiles")) {
            for (Element profile : directChildren(profiles, "profile")) {
                collectDependencies(profile, dependencies);
            }
        }
        return dependencies;
    }

    private static void collectDependencies(Element container, Set<String> dependencies) {
        for (Element dependenciesElement : directChildren(container, "dependencies")) {
            collectDependencyElements(dependenciesElement, dependencies);
        }
    }

    private static void collectDependencyElements(Element dependenciesElement, Set<String> dependencies) {
        NodeList children = dependenciesElement.getChildNodes();
        for (int index = 0; index < children.getLength(); index++) {
            Node child = children.item(index);
            if (child instanceof Element dependency && hasName(dependency, "dependency")) {
                dependencies.add(
                        directChild(dependency, "groupId").getTextContent().trim()
                                + ":"
                                + directChild(dependency, "artifactId").getTextContent().trim()
                );
            }
        }
    }

    private static Element directChild(Element parent, String name) {
        NodeList children = parent.getChildNodes();
        for (int index = 0; index < children.getLength(); index++) {
            Node child = children.item(index);
            if (child instanceof Element element && hasName(element, name)) {
                return element;
            }
        }
        throw new IllegalStateException("Missing <" + name + "> under <" + parent.getTagName() + ">");
    }

    private static List<Element> directChildren(Element parent, String name) {
        java.util.ArrayList<Element> matches = new java.util.ArrayList<>();
        NodeList children = parent.getChildNodes();
        for (int index = 0; index < children.getLength(); index++) {
            Node child = children.item(index);
            if (child instanceof Element element && hasName(element, name)) {
                matches.add(element);
            }
        }
        return List.copyOf(matches);
    }

    private static boolean hasName(Element element, String name) {
        String localName = element.getLocalName();
        return name.equals(localName != null ? localName : element.getTagName());
    }

    private static Path locateProjectRoot() {
        String basedir = System.getProperty("basedir");
        if (basedir != null && !basedir.isBlank()) {
            Path root = findProjectRoot(Path.of(basedir));
            if (root != null) {
                return root;
            }
        }

        Path workingDirectory = Path.of("").toAbsolutePath();
        Path root = findProjectRoot(workingDirectory);
        if (root != null) {
            return root;
        }
        throw new IllegalStateException(
                "Unable to locate project root containing pom.xml from basedir='"
                        + basedir
                        + "' or working directory '"
                        + workingDirectory
                        + "'"
        );
    }

    private static Path findProjectRoot(Path start) {
        Path current = start.toAbsolutePath().normalize();
        while (current != null) {
            if (Files.isRegularFile(current.resolve("pom.xml"))
                    && Files.isDirectory(current.resolve("doorhandle-server"))) {
                return current;
            }
            current = current.getParent();
        }
        return null;
    }

    private record JavaWorkaroundPattern(String description, Pattern pattern) {
    }
}
