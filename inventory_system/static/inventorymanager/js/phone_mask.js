$(document).ready(function() {
    $('#id_phone, .phone-mask').inputmask({
        mask: '+7 (999) 999-99-99',
        showMaskOnHover: false,
        showMaskOnFocus: true,
        placeholder: '_',
        clearMaskOnLostFocus: true
    });
});