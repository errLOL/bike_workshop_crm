document.addEventListener("DOMContentLoaded", function() {
    // Retrieve the data from the HTML element
    const chartDataElement = document.getElementById('inventoryChartData');
    const labelsRaw = chartDataElement.getAttribute('data-labels');
    const dataRaw = chartDataElement.getAttribute('data-data');

    const labels = JSON.parse(labelsRaw);
    const data = JSON.parse(dataRaw);

    // Create the chart
    const ctx = document.getElementById('inventoryChart').getContext('2d');
    new Chart(ctx, {
        type: 'pie',
        data: {
            labels: labels,
            datasets: [{
                label: 'Revenue',
                data: data,
                backgroundColor: ['#007bff', '#dc3545', '#ffc107', '#28a745'],
            }]
        }
    });
});