# Proguard rules for Matchai
-keep class com.matchai.agent.** { *; }
-keep class rikka.shizuku.** { *; }
-keepattributes *Annotation*
-keepattributes Signature
-dontwarn kotlin.**
-dontwarn kotlinx.serialization.**
