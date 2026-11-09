// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730.data

import okhttp3.MultipartBody
import okhttp3.ResponseBody
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query
import retrofit2.http.Streaming

interface TrackerApi {
    @GET("api/v1/server-info") suspend fun serverInfo(): ServerInfo
    @GET("api/v1/meta") suspend fun meta(): Meta

    @POST("api/v1/auth/login") suspend fun login(@Body body: LoginIn): TokenOut
    @POST("api/v1/auth/register") suspend fun register(@Body body: RegisterIn): TokenOut
    @POST("api/v1/auth/recover") suspend fun recover(@Body body: RecoverIn): TokenOut
    @POST("api/v1/auth/logout") suspend fun logout(): Unit

    @GET("api/v1/me") suspend fun me(): Me
    @PUT("api/v1/me/profile") suspend fun updateProfile(@Body body: ProfileIn): Profile
    @POST("api/v1/me/family") suspend fun addFamily(@Body body: FamilyIn): Profile
    @PUT("api/v1/me/family/{id}") suspend fun updateFamily(@Path("id") id: String, @Body body: FamilyIn): Profile
    @DELETE("api/v1/me/family/{id}") suspend fun deleteFamily(@Path("id") id: String): Profile
    @POST("api/v1/me/password") suspend fun changePassword(@Body body: PasswordIn): Unit
    @POST("api/v1/me/recovery-code") suspend fun newRecoveryCode(@Body body: PasswordOnlyIn): RecoveryCodeOut
    @GET("api/v1/me/sessions") suspend fun sessions(): List<SessionInfo>
    @DELETE("api/v1/me/sessions/{id}") suspend fun revokeSession(@Path("id") id: String): Unit
    @POST("api/v1/me/delete") suspend fun deleteAccount(@Body body: PasswordOnlyIn): Unit

    @GET("api/v1/dashboard") suspend fun dashboard(@Query("year") year: Int?): Dashboard

    @GET("api/v1/receipts")
    suspend fun receipts(
        @Query("year") year: Int? = null,
        @Query("category") category: String? = null,
        @Query("status") status: String? = null,
        @Query("beneficiary") beneficiary: String? = null,
        @Query("evaluation") evaluation: String? = null,
        @Query("q") q: String? = null,
        @Query("sort") sort: String = "date_desc",
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 50,
    ): ReceiptPage

    @Multipart
    @POST("api/v1/receipts/upload")
    suspend fun upload(@Part files: List<MultipartBody.Part>): UploadResult

    @POST("api/v1/receipts") suspend fun createReceipt(@Body body: ReceiptData): ReceiptOut
    @GET("api/v1/receipts/{id}") suspend fun receipt(@Path("id") id: String): ReceiptOut
    @PUT("api/v1/receipts/{id}") suspend fun updateReceipt(@Path("id") id: String, @Body body: ReceiptData): ReceiptOut
    @DELETE("api/v1/receipts/{id}") suspend fun deleteReceipt(@Path("id") id: String): Unit
    @POST("api/v1/receipts/{id}/reprocess") suspend fun reprocess(@Path("id") id: String): ReceiptOut

    @Streaming
    @GET("api/v1/export.zip")
    suspend fun exportZip(@Query("year") year: Int?): ResponseBody

    @Streaming
    @GET("api/v1/export.csv")
    suspend fun exportCsv(@Query("year") year: Int?): ResponseBody
}
