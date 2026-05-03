$(document).ready(function() {
    var tables = ['#suppliersTable', '#customersTable', '#productsTable', '#ordersTable', '#categoriesTable'];

    // Initialize DataTables for all tables
    tables.forEach(function(tableId) {
        $(tableId).DataTable({
            buttons: [
                {
                    extend: 'copy',
                    className: 'btn btn-primary'
                },
                {
                    extend: 'csv',
                    className: 'btn btn-primary mx-2'
                },
                {
                    extend: 'excel',
                    className: 'btn btn-primary'
                },
                {
                    extend: 'pdf',
                    className: 'btn btn-primary mx-2'
                },
                {
                    extend: 'print',
                    className: 'btn btn-primary'
                }
            ],
            responsive: true,
            language: {
                search: "_INPUT_",
                searchPlaceholder: "Search...",
            },
            lengthMenu: [[10, 25, 50, -1], [10, 25, 50, "All"]],
        });
    });

    // Adding click event listener to all rows in the different tables
    $('table').on('click', 'tbody tr', function() {
        var id = $(this).attr('data-id');  // Get the ID of the clicked row
        var tableType = $(this).closest('table').data('type');  // Get the table type (e.g., supplier, customer)

        if (id && tableType) {
            // Redirect based on the table type
            window.location.href = `/${tableType}/${id}`;
            
        }
    });

    // Append buttons to the card header (optional for UI enhancement)
    $('table').DataTable().buttons().container()
        .appendTo('.card-header');
});