plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.ksp)
}

android {
    namespace = "dev.smallnext.app"
    // Compose BOM 2026.09 libraries require compiling against API 37.
    compileSdk = 37
    buildToolsVersion = "36.0.0"

    defaultConfig {
        applicationId = "dev.smallnext.app"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures {
        buildConfig = true
        compose = true
    }
}

// The app bundles the repository's single flag registry; no copy is committed.
abstract class BundleFeatureFlags : DefaultTask() {
    @get:InputFile
    @get:PathSensitive(PathSensitivity.NONE)
    abstract val registry: RegularFileProperty

    @get:OutputDirectory
    abstract val assets: DirectoryProperty

    @TaskAction
    fun copy() {
        registry.get().asFile.copyTo(assets.file("feature-flags.json").get().asFile, overwrite = true)
    }
}

val bundleFeatureFlags = tasks.register<BundleFeatureFlags>("bundleFeatureFlags") {
    registry.set(rootProject.layout.projectDirectory.file("../../config/feature-flags.json"))
}

androidComponents {
    onVariants { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(bundleFeatureFlags, BundleFeatureFlags::assets)
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
}

dependencies {
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.material3)
    implementation(libs.compose.ui.tooling.preview)
    debugImplementation(libs.compose.ui.tooling)
    implementation(libs.activity.compose)
    implementation(libs.room.runtime)
    implementation(libs.room.ktx)
    ksp(libs.room.compiler)
    implementation(libs.retrofit)
    implementation(libs.retrofit.gson)
    implementation(libs.okhttp)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.runner)
}

// Compiler outputs can be cached; CI tests must execute on each runner/device.
if (System.getenv("CI") == "true") {
    tasks.withType<org.gradle.api.tasks.testing.Test>().configureEach {
        outputs.upToDateWhen { false }
        outputs.cacheIf { false }
    }
    tasks.matching {
        it.name.startsWith("connected") && it.name.endsWith("AndroidTest")
    }.configureEach {
        outputs.upToDateWhen { false }
        outputs.cacheIf { false }
    }
}
