FROM maven:3.9.9-eclipse-temurin-17 AS build
WORKDIR /workspace
COPY pom.xml ./
COPY doorhandle-dependencies/pom.xml doorhandle-dependencies/pom.xml
COPY doorhandle-framework/pom.xml doorhandle-framework/pom.xml
COPY doorhandle-module-app/pom.xml doorhandle-module-app/pom.xml
COPY doorhandle-server/pom.xml doorhandle-server/pom.xml
RUN mvn -q -DskipTests dependency:go-offline -pl doorhandle-server -am
COPY doorhandle-server/src doorhandle-server/src
COPY doorhandle-module-app/src doorhandle-module-app/src
RUN mvn -q -DskipTests package -pl doorhandle-server -am

FROM eclipse-temurin:17-jre-alpine
RUN addgroup -S app && adduser -S app -G app \
    && apk add --no-cache curl
WORKDIR /app
RUN mkdir -p /app/uploads /app/logs && chown -R app:app /app
COPY --chown=app:app --from=build /workspace/doorhandle-server/target/doorhandle-server-*.jar app.jar
USER app
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8080/actuator/health || exit 1
ENTRYPOINT ["sh", "-c", "java $JAVA_OPTS -jar /app/app.jar"]
