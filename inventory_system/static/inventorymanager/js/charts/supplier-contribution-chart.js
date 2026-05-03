document.addEventListener("DOMContentLoaded", function() {
    // Retrieve the data from the HTML element
    const chartDataElement = document.getElementById('supplierContributionChartData');
    const labelsRaw = chartDataElement.getAttribute('data-labels');
    const dataRaw = chartDataElement.getAttribute('data-data');

    const labels = JSON.parse(labelsRaw);
    const data = JSON.parse(dataRaw);

    // Create the chart
    const ctx = document.getElementById('supplierContributionChart').getContext('2d');
    new Chart(ctx, {
        type: 'pie',
        data: {
            labels: labels,
            datasets: [{
                label: 'Supplier Contribution',
                data: data,
                backgroundColor: ['#007bff', '#dc3545', '#ffc107', '#28a745'],
            }]
        },
        options: {
            tooltips: {
                callbacks: {
                    label: function(tooltipItem, data) {
                        const dataset = data.datasets[tooltipItem.datasetIndex];
                        const currentValue = dataset.data[tooltipItem.index];
                        const label = data.labels[tooltipItem.index];
                        return `${label}: ${currentValue}%`;  // Display label with percentage symbol
                    }
                }
            }
        }
    });
});