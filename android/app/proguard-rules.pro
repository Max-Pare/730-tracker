# kotlinx.serialization: keep generated serializers
-keepattributes *Annotation*, InnerClasses, Signature, Exceptions
-dontnote kotlinx.serialization.**
-keepclassmembers @kotlinx.serialization.Serializable class ** {
    *** Companion;
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class io.github.maxpare.tracker730.**$$serializer { *; }
# Retrofit service interfaces
-keep,allowobfuscation,allowshrinking interface io.github.maxpare.tracker730.data.TrackerApi
-keep,allowobfuscation,allowshrinking class kotlin.coroutines.Continuation
