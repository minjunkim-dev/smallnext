package dev.smallnext.app.network

import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.GET

data class HealthResponse(val status: String)

interface APIService {
    @GET("health")
    suspend fun health(): HealthResponse
}

object APIClient {
    fun create(baseUrl: String): APIService =
        Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(OkHttpClient())
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(APIService::class.java)
}
