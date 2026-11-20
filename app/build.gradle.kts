plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "tech.cecypo.smsbridge"
    compileSdk = 36

    defaultConfig {
        applicationId = "tech.cecypo.smsbridge"
        minSdk = 35  // Android 15 and later only
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"
    }

    val ksPath = System.getenv("SIGNING_KEYSTORE_PATH")
    val ksPass = System.getenv("SIGNING_PASSWORD")
    signingConfigs {
        if (!ksPath.isNullOrEmpty() && !ksPass.isNullOrEmpty()) {
            create("release") {
                storeFile = file(ksPath)
                storeType = "pkcs12"
                storePassword = ksPass
                keyAlias = "smsbridge"
                keyPassword = ksPass
            }
        }
    }

    buildTypes {
        release {
            // Unsigned when the env vars are absent (local or PR build still configures).
            signingConfigs.findByName("release")?.let { signingConfig = it }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.work:work-runtime-ktx:2.10.0")
    implementation("androidx.swiperefreshlayout:swiperefreshlayout:1.1.0")
    testImplementation("junit:junit:4.13.2")
    // android.jar org.json is a stub that throws in JVM unit tests; real impl for tests only
    testImplementation("org.json:json:20240303")
}
