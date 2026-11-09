// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** Wire models for the server's JSON API (`/api/v1`). Field names follow the server (snake_case). */

@Serializable
data class ServerInfo(
    val name: String,
    val version: String,
    val api: Int,
    @SerialName("registration_mode") val registrationMode: String,
    @SerialName("needs_setup") val needsSetup: Boolean,
    @SerialName("max_upload_mb") val maxUploadMb: Int = 20,
)

@Serializable
data class CategoryMeta(
    val code: String,
    val label: String,
    val group: String? = null,
    @SerialName("trace_exempt") val traceExempt: Boolean = false,
    val hint: String = "",
)

@Serializable
data class CodeLabel(val code: String, val label: String)

@Serializable
data class Meta(
    val categories: List<CategoryMeta>,
    @SerialName("payment_methods") val paymentMethods: List<CodeLabel>,
    val statuses: List<CodeLabel>,
    val relations: List<CodeLabel>,
)

@Serializable
data class UserOut(
    val id: String,
    val username: String,
    val role: String,
    @SerialName("created_at") val createdAt: String,
) {
    val isAdmin: Boolean get() = role == "admin"
}

@Serializable
data class TokenOut(
    val token: String,
    val user: UserOut,
    @SerialName("recovery_code") val recoveryCode: String? = null,
)

@Serializable
data class LoginIn(
    val username: String,
    val password: String,
    @SerialName("device_name") val deviceName: String? = null,
)

@Serializable
data class RegisterIn(
    val username: String,
    val password: String,
    val invite: String? = null,
    @SerialName("device_name") val deviceName: String? = null,
)

@Serializable
data class RecoverIn(
    val username: String,
    @SerialName("recovery_code") val recoveryCode: String,
    @SerialName("new_password") val newPassword: String,
    @SerialName("device_name") val deviceName: String? = null,
)

@Serializable
data class PasswordIn(
    @SerialName("current_password") val currentPassword: String,
    @SerialName("new_password") val newPassword: String,
)

@Serializable
data class PasswordOnlyIn(@SerialName("current_password") val currentPassword: String)

@Serializable
data class RecoveryCodeOut(@SerialName("recovery_code") val recoveryCode: String)

@Serializable
data class OcrItem(
    val description: String = "",
    @SerialName("amount_cents") val amountCents: Long = 0,
    val deductible: Boolean? = null,
)

@Serializable
data class OcrInfo(
    val text: String = "",
    val confidence: Double = 0.0,
    val engine: String = "",
    @SerialName("field_confidence") val fieldConfidence: Map<String, Double> = emptyMap(),
    val warnings: List<String> = emptyList(),
    val items: List<OcrItem> = emptyList(),
    @SerialName("processed_at") val processedAt: String? = null,
)

@Serializable
data class ReceiptData(
    val status: String = "bozza",
    val date: String? = null,
    @SerialName("amount_cents") val amountCents: Long? = null,
    @SerialName("deductible_cents") val deductibleCents: Long? = null,
    @SerialName("provider_name") val providerName: String? = null,
    @SerialName("provider_vat") val providerVat: String? = null,
    @SerialName("provider_tax_code") val providerTaxCode: String? = null,
    @SerialName("document_number") val documentNumber: String? = null,
    val category: String? = null,
    @SerialName("payment_method") val paymentMethod: String = "sconosciuto",
    @SerialName("ssn_provider") val ssnProvider: Boolean = false,
    val beneficiary: String = "self",
    @SerialName("patient_tax_code") val patientTaxCode: String? = null,
    val description: String? = null,
    val notes: String? = null,
    val tags: List<String> = emptyList(),
    val source: String = "manuale",
    @SerialName("original_filename") val originalFilename: String? = null,
    val ocr: OcrInfo? = null,
) {
    /** True when the OCR was unsure about [field] (or did not find it) on an unreviewed draft. */
    fun isLowConfidence(field: String): Boolean =
        status == "bozza" && source == "ocr" && (ocr?.fieldConfidence?.get(field) ?: 0.0) < 0.6
}

@Serializable
data class EvaluationOut(
    val status: String,
    val label: String,
    val group: String? = null,
    @SerialName("eligible_cents") val eligibleCents: Long = 0,
    val reasons: List<String> = emptyList(),
    val warnings: List<String> = emptyList(),
)

@Serializable
data class ReceiptOut(
    val id: String,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String,
    val data: ReceiptData,
    @SerialName("beneficiary_label") val beneficiaryLabel: String = "",
    val evaluation: EvaluationOut,
    @SerialName("has_scan") val hasScan: Boolean = false,
    @SerialName("has_original") val hasOriginal: Boolean = false,
    @SerialName("original_type") val originalType: String? = null,
    val duplicates: List<String> = emptyList(),
)

@Serializable
data class ReceiptPage(
    val items: List<ReceiptOut>,
    val total: Int,
    val page: Int,
    val pages: Int,
    @SerialName("total_amount_cents") val totalAmountCents: Long,
)

@Serializable
data class UploadErrorOut(val filename: String? = null, val message: String)

@Serializable
data class UploadResult(val created: List<ReceiptOut>, val errors: List<UploadErrorOut> = emptyList())

@Serializable
data class Bucket(
    val key: String,
    val label: String,
    val count: Int = 0,
    @SerialName("total_cents") val totalCents: Long = 0,
    @SerialName("eligible_cents") val eligibleCents: Long = 0,
)

@Serializable
data class Issue(
    @SerialName("receipt_id") val receiptId: String,
    val title: String,
    val message: String,
    val severity: String,
)

@Serializable
data class Summary(
    val year: Int,
    @SerialName("return_label") val returnLabel: String,
    @SerialName("receipts_count") val receiptsCount: Int = 0,
    @SerialName("drafts_count") val draftsCount: Int = 0,
    @SerialName("to_verify_count") val toVerifyCount: Int = 0,
    @SerialName("non_deductible_count") val nonDeductibleCount: Int = 0,
    @SerialName("total_spent_cents") val totalSpentCents: Long = 0,
    @SerialName("sanitarie_eligible_cents") val sanitarieEligibleCents: Long = 0,
    @SerialName("sanitarie_base_cents") val sanitarieBaseCents: Long = 0,
    @SerialName("sanitarie_detraction_cents") val sanitarieDetractionCents: Long = 0,
    @SerialName("vet_eligible_cents") val vetEligibleCents: Long = 0,
    @SerialName("vet_detraction_cents") val vetDetractionCents: Long = 0,
    @SerialName("detraction_total_cents") val detractionTotalCents: Long = 0,
    @SerialName("uncertain_cents") val uncertainCents: Long = 0,
    @SerialName("non_deductible_cents") val nonDeductibleCents: Long = 0,
    @SerialName("franchise_cents") val franchiseCents: Long = 12911,
    @SerialName("franchise_remaining_cents") val franchiseRemainingCents: Long = 0,
    @SerialName("instalments_possible") val instalmentsPossible: Boolean = false,
    @SerialName("by_month") val byMonth: List<Bucket> = emptyList(),
    @SerialName("by_category") val byCategory: List<Bucket> = emptyList(),
    @SerialName("by_beneficiary") val byBeneficiary: List<Bucket> = emptyList(),
    val issues: List<Issue> = emptyList(),
)

@Serializable
data class Dashboard(
    val years: List<Int>,
    @SerialName("drafts_total") val draftsTotal: Int = 0,
    val summary: Summary,
)

@Serializable
data class FamilyMember(
    val id: String = "",
    val name: String,
    @SerialName("tax_code") val taxCode: String? = null,
    val relation: String = "altro",
    val dependent: Boolean = true,
)

@Serializable
data class FamilyIn(
    val name: String,
    @SerialName("tax_code") val taxCode: String? = null,
    val relation: String = "altro",
    val dependent: Boolean = true,
)

@Serializable
data class Profile(
    @SerialName("full_name") val fullName: String? = null,
    @SerialName("tax_code") val taxCode: String? = null,
    val family: List<FamilyMember> = emptyList(),
) {
    fun beneficiaryOptions(): List<Pair<String, String>> =
        listOf("self" to (fullName ?: "Me stesso/a")) +
            family.map { it.id to (it.name + if (it.dependent) "" else " (non a carico)") }
}

@Serializable
data class ProfileIn(
    @SerialName("full_name") val fullName: String? = null,
    @SerialName("tax_code") val taxCode: String? = null,
)

@Serializable
data class Me(val user: UserOut, val profile: Profile)

@Serializable
data class SessionInfo(
    val id: String,
    val kind: String,
    val label: String? = null,
    @SerialName("created_at") val createdAt: String,
    @SerialName("last_seen_at") val lastSeenAt: String,
    val current: Boolean = false,
)
