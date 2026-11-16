const form = document.querySelector('form')
const email = form.elements.namedItem('email')
const consent = form.elements.namedItem('reply_consent')
function validateConsent() {
  consent.setCustomValidity(email.value.trim() && !consent.checked ? 'Please consent to a reply, or leave the email blank.' : '')
}
email.addEventListener('input', validateConsent)
consent.addEventListener('change', validateConsent)
form.addEventListener('submit', (event) => {
  validateConsent()
  if (!form.reportValidity()) event.preventDefault()
})
