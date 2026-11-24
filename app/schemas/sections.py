"""Editable site sections.

Each key in SECTIONS is one block of the public site the owner can edit in the
admin panel. The model validates what is saved and its JSON Schema drives the
admin form, so adding a field here adds it to the editor too.
"""

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, ValidationInfo, field_validator

from app.schemas.common import (
    BrandIconUrl,
    CamelModel,
    Copy,
    Cta,
    ExternalUrl,
    Href,
    ImageUrl,
    Line,
    Short,
    Stat,
    widget,
)

NavKey = Literal["home", "projects", "about", "journal", "contact"]
HomeBlock = Literal[
    "about", "stack", "work", "services", "pricing", "testimonials", "cta", "numbers", "journal"
]
ContactIcon = Literal["rocket", "code", "server", "bulb", "sparkles"]

Lines = Annotated[list[Line], Field(max_length=30)]


# --- global -------------------------------------------------------------------


class SiteSettings(CamelModel):
    name: Short = Field(description="Your full name, used in titles and accessible labels.")
    wordmark: Short = Field(
        description="Giant letters in the hero and footer. Short words fit best."
    )
    logo: Short = Field(description="Small logo text in the header.")
    email: Annotated[str, Field(max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
    year: Annotated[str, Field(max_length=10)]
    github: ExternalUrl
    description: Line = Field(description="Default meta description for search engines.")


class NavItem(CamelModel):
    key: NavKey
    title: Short
    href: Href


class Navigation(CamelModel):
    items: Annotated[list[NavItem], Field(max_length=10)]


class FaqItem(CamelModel):
    question: Line
    answer: Copy


class FaqReel(CamelModel):
    image: ImageUrl
    label: Short
    meta: Short
    href: Href


class Faq(CamelModel):
    title: Short
    reel: FaqReel
    items: Annotated[list[FaqItem], Field(max_length=30)]


class FooterCredit(CamelModel):
    label: Short
    link_label: Short
    href: Href


DEFAULT_FOOTER_PROFILE_IMAGE = (
    "https://res.cloudinary.com/vmfn84y1/image/upload/"
    "f_auto,q_auto,c_fill,g_face,w_256,h_256/"
    "v1793902790/chamathdilshan.dev/shared/hcc5l3yfawhijzq2vbsc-15.png"
)


class Footer(CamelModel):
    heading: Short
    cta: Cta
    profile_image: ImageUrl = DEFAULT_FOOTER_PROFILE_IMAGE
    copyright: Line
    credit: FooterCredit


# --- home ---------------------------------------------------------------------


class LayoutEntry(CamelModel):
    section: HomeBlock
    visible: bool = True


class HomeLayout(CamelModel):
    """Order and visibility of the home page sections below the hero."""

    sections: Annotated[list[LayoutEntry], Field(max_length=20)]


class HeroIntro(CamelModel):
    line1: Line
    line2: Line
    line2_dim: Line = Field(title="Line 2 (dimmed part)")
    line3_dim: Line = Field(title="Line 3 (dimmed)")


class HomeHero(CamelModel):
    image: ImageUrl
    image_alt: Line = ""
    intro: HeroIntro
    cta: Cta
    disciplines: Lines


class HomeAbout(CamelModel):
    title: Short
    aside: Short
    statement: Copy
    image: ImageUrl
    image_alt: Line = ""
    pre: Copy
    post: Copy
    results: Annotated[list[Stat], Field(max_length=8)]
    cta: Cta


class HomeWork(CamelModel):
    title: Short
    aside: Short
    cta: Cta
    see_all_thumb: ImageUrl = Field(title="“See all” thumbnail")


class ServiceItem(CamelModel):
    number: Annotated[str, Field(max_length=10)]
    title: Short
    heading: Short
    body: Copy
    image: ImageUrl


class HomeServices(CamelModel):
    title: Short
    aside: Short
    statement: Copy
    poster: ImageUrl
    poster_alt: Line = ""
    cta: Cta
    items: Annotated[list[ServiceItem], Field(max_length=12)]


class PricingPlan(CamelModel):
    name: Short
    description: Line
    price: Annotated[str, Field(max_length=20)]
    unit: Annotated[str, Field(max_length=30)]
    tone: Literal["light", "dark"] = "light"
    included: Lines


class HomePricing(CamelModel):
    title: Short
    aside: Short
    included_heading: Short
    plans: Annotated[list[PricingPlan], Field(max_length=6)]
    cta: Cta


class Testimonial(CamelModel):
    quote: Copy
    name: Short
    role: Short
    company: Short
    project: Annotated[
        str,
        Field(
            max_length=80,
            description="The case study this quote is about.",
            json_schema_extra=widget("project-ref"),
        ),
    ] = ""


class HomeTestimonials(CamelModel):
    title: Short
    aside: Short
    items: Annotated[list[Testimonial], Field(max_length=20)]


class HomeCta(CamelModel):
    marquee: Line
    background: ImageUrl
    background_alt: Line = ""
    action: Cta


class NumberItem(CamelModel):
    value: Annotated[str, Field(max_length=20)]
    title: Short
    body: Copy


class HomeNumbers(CamelModel):
    title: Short
    aside: Short
    items: Annotated[list[NumberItem], Field(max_length=8)]


class HomeJournal(CamelModel):
    title: Short
    aside: Short
    cta: Cta


# --- pages --------------------------------------------------------------------


class ListPage(CamelModel):
    title: Annotated[
        list[Short],
        Field(min_length=2, max_length=2, description="Two lines, e.g. Latest / Projects."),
    ]
    image: ImageUrl
    image_alt: Line = ""
    description: Line
    list_title: Short
    list_aside: Short


class AboutPage(CamelModel):
    title: Short
    image: ImageUrl
    image_alt: Line = ""
    label: Short
    blurb: Line


class AboutExperience(CamelModel):
    """Heading for the work timeline. The roles themselves are managed under Experience."""

    title: Short
    aside: Short


class ProcessStep(CamelModel):
    number: Annotated[str, Field(max_length=10)]
    title: Short
    body: Copy
    included: Lines


class AboutProcess(CamelModel):
    title: Short
    aside: Short
    statement: Copy
    image: ImageUrl
    image_alt: Line = ""
    steps: Annotated[list[ProcessStep], Field(max_length=10)]


class ToolboxItem(CamelModel):
    name: Short
    role: Short
    image: BrandIconUrl | None = Field(
        default=None,
        title="Logo",
        description=(
            "Search theSVG by tool name, or paste a logo URL. "
            "Use a light variant on the dark background."
        ),
    )

    @field_validator("image", mode="before")
    @classmethod
    def _replace_placeholder(cls, value: object, info: ValidationInfo) -> object:
        """Upgrade old stock photos when reading or saving existing toolbox content."""
        if isinstance(value, str) and value.startswith("/images/placeholders/"):
            slugs = {
                "VS Code": "visual-studio-code",
                "Figma": "figma",
                "Docker": "docker",
                "GitHub Actions": "github-actions",
                "Supabase": "supabase",
            }
            slug = slugs.get(info.data.get("name", ""))
            return f"https://thesvg.org/icons/{slug}/default.svg" if slug else None
        return value


class AboutToolbox(CamelModel):
    title: Short
    aside: Short
    items: Annotated[list[ToolboxItem], Field(max_length=20)]


class RecognitionRow(CamelModel):
    count: Annotated[str, Field(max_length=10)]
    award: Short
    project: Short
    result: Short


class AboutRecognition(CamelModel):
    title: Short
    aside: Short
    rows: Annotated[list[RecognitionRow], Field(max_length=30)]


class AboutStack(CamelModel):
    """Heading for the skills grid. The skills themselves are managed under Skills."""

    title: Short
    aside: Short


class ContactCategory(CamelModel):
    value: Annotated[str, Field(max_length=60, pattern=r"^[a-z0-9-]+$")]
    title: Short
    description: Line
    icon: ContactIcon = "sparkles"


class ContactPage(CamelModel):
    title: Short
    intro: Copy
    image: ImageUrl
    image_alt: Line = ""
    categories: Annotated[list[ContactCategory], Field(max_length=12)]


# --- registry -----------------------------------------------------------------


@dataclass(frozen=True)
class SectionSpec:
    key: str
    title: str
    group: str
    description: str
    model: type[CamelModel]


_SPECS = [
    SectionSpec("site", "Site settings", "Global", "Name, wordmark, email and SEO description.",
                SiteSettings),
    SectionSpec("navigation", "Navigation", "Global", "Menu labels in the header and footer.",
                Navigation),
    SectionSpec("faq", "FAQ", "Global", "Questions shown above the footer on every page.", Faq),
    SectionSpec(
        "footer", "Footer", "Global", "Heading, profile image, call to action and copyright line.",
                Footer),
    SectionSpec("home.layout", "Home layout", "Home",
                "Order and visibility of the home page sections.", HomeLayout),
    SectionSpec("home.hero", "Hero", "Home", "Full-screen opening image and intro lines.",
                HomeHero),
    SectionSpec("home.about", "About", "Home", "Statement, image and headline results.",
                HomeAbout),
    SectionSpec("home.work", "Selected work", "Home",
                "Heading for the project stack. Projects are managed under Projects.", HomeWork),
    SectionSpec("home.services", "Services", "Home", "Statement and service rows.",
                HomeServices),
    SectionSpec("home.pricing", "Engagements", "Home", "Pricing plans and what they include.",
                HomePricing),
    SectionSpec("home.testimonials", "Testimonials", "Home", "Quotes from clients.",
                HomeTestimonials),
    SectionSpec(
        "home.cta",
        "Call to action",
        "Home",
        "Dark band with the brand mark and contact action.",
        HomeCta,
    ),
    SectionSpec("home.numbers", "In numbers", "Home", "Four headline figures.", HomeNumbers),
    SectionSpec("home.journal", "Journal", "Home",
                "Heading for the latest articles. Articles are managed under Journal.",
                HomeJournal),
    SectionSpec("page.projects", "Projects page", "Pages", "Hero and list heading on /projects.",
                ListPage),
    SectionSpec("page.blog", "Journal page", "Pages", "Hero and list heading on /blog.",
                ListPage),
    SectionSpec("page.about", "About hero", "Pages", "Hero on /about.", AboutPage),
    SectionSpec("about.experience", "About · Experience", "Pages",
                "Heading for the work timeline. Roles are managed under Experience.",
                AboutExperience),
    SectionSpec("about.process", "About · Process", "Pages", "Process statement and steps.",
                AboutProcess),
    SectionSpec(
        "about.toolbox", "About · Toolbox", "Pages",
        "Scrolling tool logos. Add, remove and reorder tools; search theSVG for each logo.",
        AboutToolbox,
    ),
    SectionSpec("about.recognition", "About · Recognition", "Pages", "Awards and certificates.",
                AboutRecognition),
    SectionSpec("about.stack", "About · Stack", "Pages",
                "Heading for the skills grid. Skills are managed under Skills.", AboutStack),
    SectionSpec("page.contact", "Contact page", "Pages", "Intro, image and form categories.",
                ContactPage),
]

SECTIONS: dict[str, SectionSpec] = {spec.key: spec for spec in _SPECS}
