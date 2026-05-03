document.addEventListener("DOMContentLoaded", function() {
    // Retrieve the data from the HTML element
    const chartDataElement = document.getElementById('custumerOrdersChartData');
    const labelsRaw = chartDataElement.getAttribute('data-labels');
    const dataRaw = chartDataElement.getAttribute('data-data');

    const labels = JSON.parse(labelsRaw);
    const data = JSON.parse(dataRaw);

    // Create the chart
    const ctx = document.getElementById('customerOrdersChart').getContext('2d');
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Customer Revenue',
                data: data,
                borderColor: 'rgba(75, 192, 192, 1)',
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                borderWidth: 2,
                fill: true,
            }]
        },
        options: {
            responsive: true,
            scales: {
                yAxes: [{
                    ticks: {
                      min: 0,
                    },
                    gridLines: {
                      display: true
                    }
                  }],
            },
            tooltips: {
                callbacks: {
                    label: function(tooltipItem, data) {
                        const dataset = data.datasets[tooltipItem.datasetIndex];
                        const currentValue = dataset.data[tooltipItem.index];
                        return `Revenue: ${currentValue.toLocaleString()}`; 
                    }
                }
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top'
                }
            }
        }
    });
});