using Microsoft.AspNetCore.Mvc;
using System.Text.Json;
using web_app.Data;
using web_app.Models;
using web_app.Services;

namespace web_app.Controllers
{
    public class PredictionsController : Controller
    {
        private readonly AppDbContext _db;
        private readonly FastApiClient _api;

        public PredictionsController(AppDbContext db, FastApiClient api)
        {
            _db = db;
            _api = api;
        }

        [HttpGet]
        public IActionResult Create() => View();

        [HttpPost]
        public async Task<IActionResult> Create([FromForm] Dictionary<string, string> features)
        {
            var featureObj = new Dictionary<string, object>
            {
                ["countryCode"] = features["countryCode"],
                ["PaperlessBill"] = features["PaperlessBill"],
                ["InvoiceAmount"] = features["InvoiceAmount"],
                ["InvoiceMonth"] = features["InvoiceMonth"],
                ["InvoiceDayOfWeek"] = features["InvoiceDayOfWeek"]
            };

            var result = await _api.PredictAsync(featureObj);

            var rec = new PredictionRecord
            {
                CreatedAt = DateTime.UtcNow,
                FeaturesJson = JsonSerializer.Serialize(features),
                Prediction = result.prediction,
                Probability = result.probability
            };

            _db.Predictions.Add(rec);
            await _db.SaveChangesAsync();

            return RedirectToAction(nameof(History));
        }

        [HttpGet]
        public IActionResult History()
        {
            var items = _db.Predictions
                .OrderByDescending(x => x.Id)
                .Take(50)
                .ToList();

            return View(items);
        }
    }
}
