# Inji Certify Issuer Plugin Module

This directory contains the custom **Inji Certify** SPI Data-Provider Plugin (`IssuerDataProviderPlugin`), implementing the custom student record data retrieval and clearance gate checks.

---

## 1. Directory Structure

```
src/issuer/
├── pom.xml               # Java 21 Maven project configuration
├── src/
│   ├── main/java/        #   - IssuerDataProviderPlugin implementation
│   └── test/java/        #   - Comprehensive JUnit test suite
└── README.md
```

*(Note: Container build recipes are located in `docker/Dockerfile.certify`)*

---

## 2. Developer Experience (DX) & Inner Loops

When developing or modifying the DataProvider SPI plugin, choose the feedback loop that fits your task:

### Loop 1: Fast Inner Loop — Unit Testing (~3s)
Run JUnit tests directly from `src/issuer`:
```bash
cd src/issuer
mvn test
```
*(Or in Docker if Maven is not installed locally):*
```bash
docker run --rm -v "$PWD/src/issuer:/src" -w /src maven:3.9-eclipse-temurin-21 mvn test
```
Tests in-memory HTTP responses, error mappings, and JSON escaping in **~3 seconds**.

---

### Loop 2: Hot JAR Mount with Compiler Container (~2s Reload)
For rapid local iteration without rebuilding Docker images or requiring host Maven:

1. **Compile using the compiler container:**
   ```bash
   ./scripts/build.sh --jar-only
   ```
   *(Or using host Maven if installed: `mvn -f src/issuer/pom.xml package -DskipTests`)*

2. **Mount the JAR locally via `compose.override.yaml`:**
   ```yaml
   services:
     service:
       volumes:
         - ./src/issuer/target/issuer-data-provider-plugin.jar:/home/inji/additional_jars/issuer-data-provider-plugin.jar:ro
   ```

3. **Start or reload Inji Certify:**
   ```bash
   docker compose up -d
   # Or reload after code changes:
   docker compose restart service
   ```

---

### Loop 3: Multi-Stage Release Build
To package all standalone, production-ready container images and push them:
```bash
# Build all images locally
./scripts/build.sh

# Or build and push to GHCR:
./scripts/build.sh --tag v0.2.0 --push
```
`docker/Dockerfile.certify` is a 2-stage Dockerfile that builds the JAR in stage 1 and bakes it into `injistack/inji-certify-with-plugins:0.14.0` in stage 2 without requiring host mounts in production.
