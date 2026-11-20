package tech.cecypo.smsbridge

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.util.AttributeSet
import android.view.View
import android.graphics.Typeface

/** 14 stacked bars: matched, unmatched, other. Console palette from colors.xml. */
class BarChartView(context: Context, attrs: AttributeSet? = null) : View(context, attrs) {
    private var days: List<DayCount> = emptyList()
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val label = Paint(Paint.ANTI_ALIAS_FLAG).apply { textSize = 11f * resources.displayMetrics.scaledDensity; textAlign = Paint.Align.CENTER }
    private val cMatched = context.getColor(R.color.white)
    private val cUnmatched = context.getColor(R.color.gray)
    private val cOther = context.getColor(R.color.chart_other)

    init { label.color = context.getColor(R.color.gray); label.typeface = Typeface.MONOSPACE }

    fun setData(d: List<DayCount>) { days = d; invalidate() }

    override fun onDraw(canvas: Canvas) {
        if (days.isEmpty()) return
        val labelH = label.textSize * 1.5f
        val chartH = height - labelH
        val max = maxOf(1, days.maxOf { it.matched + it.unmatched + it.ignored + it.duplicate + it.error })
        val slot = width.toFloat() / days.size
        val bar = slot * 0.7f
        days.forEachIndexed { i, d ->
            val left = i * slot + (slot - bar) / 2
            var bottom = chartH
            for ((n, color) in listOf(d.matched to cMatched, d.unmatched to cUnmatched, (d.ignored + d.duplicate + d.error) to cOther)) {
                if (n == 0) continue
                val h = chartH * n / max
                paint.color = color
                canvas.drawRect(left, bottom - h, left + bar, bottom, paint)
                bottom -= h
            }
            if (i % 2 == 0) canvas.drawText(d.date.takeLast(2), left + bar / 2, height - label.textSize * 0.3f, label)
        }
    }
}
